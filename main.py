# main.py v3 — aggiunge multi-timeframe, RS vs SP500, earnings warning

from flask import Flask, render_template, jsonify
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def sanitize(obj):
    """Sostituisce NaN/Inf con None ricorsivamente — JSON non accetta NaN."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize(i) for i in obj]
    return obj

import config
from modules.data_fetcher    import DataFetcher
from modules.indicators      import compute_indicators
from modules.scorer          import score_ticker
from modules.signals         import generate_signal
from modules.news_sentiment  import NewsSentiment
from modules.backtester      import Backtester
from modules.ai_analyst      import AIAnalyst

ai_analyst = AIAnalyst()

app     = Flask(__name__)
fetcher = DataFetcher()
news_a  = NewsSentiment()

# ─────────────────────────────────────────────────────────────────
# REGIME (cached per sessione tramite NewsSentiment)
# ─────────────────────────────────────────────────────────────────
def _get_regime():
    vix = news_a.get_vix().get("value", 20)
    fg  = news_a.get_fear_greed().get("value", 50)
    return float(vix), float(fg)

# ─────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", watchlist=config.WATCHLIST,
                           capital=config.CAPITAL)

@app.route("/api/analyze/<ticker>")
def analyze(ticker):
    ticker = ticker.upper().strip()
    try:
        df_raw = fetcher.get_historical(ticker)
        if df_raw is None:
            return jsonify({"error": f"Dati non disponibili per {ticker}"}), 404

        df = compute_indicators(df_raw)

        # Dati extra (tutti in parallelo concettuale)
        vix_val, fg_val = _get_regime()
        rs_data         = fetcher.get_relative_strength(ticker)
        earnings_data   = fetcher.get_earnings_date(ticker)
        mtf_data        = fetcher.get_multitimeframe(ticker)
        sent            = news_a.get_full_sentiment(ticker)
        price           = fetcher.get_current_price(ticker)
        info            = fetcher.get_company_info(ticker)

        # Declassa automaticamente se weekly ribassista e daily bullish
        mtf_adj  = _mtf_score_adjustment(mtf_data)

        score = score_ticker(df, ticker,
                             vix=vix_val, fg=fg_val,
                             rs_data=rs_data,
                             earnings_data=earnings_data)

        # Applica aggiustamento multi-timeframe e aggiorna score_steps
        if mtf_adj != 0:
            old_s = score["score"]
            score["score"] = round(min(max(old_s + mtf_adj, 0), 100), 1)
            score["explanation"] += f" | MTF: {mtf_adj:+d}pts"
            if score["score"] < config.SIGNAL_BUY_THRESHOLD and score["signal"] == "BUY":
                score["signal"] = "WATCH"
            # Aggiorna score_steps con il passo MTF
            steps = score.get("score_steps", [])
            if steps:
                steps.append({
                    "label": "Multi-timeframe",
                    "value": score["score"],
                    "delta": mtf_adj,
                })
                score["score_steps"] = steps

        sig  = generate_signal(df, score)
        last = df.iloc[-1]

        return jsonify(sanitize({
            "ticker":       ticker,
            "price":        price,
            "info":         info,
            "score":        score,
            "signal":       sig,
            "sentiment":    sent,
            "multitimeframe": mtf_data,
            "relative_strength": rs_data,
            "earnings":     earnings_data,
            "indicators": {
                "rsi":          round(float(last.get("RSI",          50)), 1),
                "macd":         round(float(last.get("MACD",          0)), 3),
                "macd_hist":    round(float(last.get("MACD_hist",     0)), 3),
                "macd_signal":  round(float(last.get("MACD_signal",   0)), 3),
                "bb_upper":     round(float(last.get("BB_upper",      0)), 2),
                "bb_mid":       round(float(last.get("BB_mid",        0)), 2),
                "bb_lower":     round(float(last.get("BB_lower",      0)), 2),
                "bb_position":  round(float(last.get("BB_position", 0.5)), 3),
                "atr":          round(float(last.get("ATR",           0)), 2),
                "adx":          round(float(last.get("ADX",           0)), 1),
                "di_plus":      round(float(last.get("DI_plus",       0)), 1),
                "di_minus":     round(float(last.get("DI_minus",      0)), 1),
                "volume_ratio": round(float(last.get("Volume_ratio",  1)), 2),
                "ma20":         round(float(last.get("MA20",          0)), 2),
                "ma50":         round(float(last.get("MA50",          0)), 2),
                "ma200":        round(float(last.get("MA200",         0)), 2),
            },
            "chart_data": _get_chart_data(df),
        }))
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/scan")
def scan():
    vix_val, fg_val = _get_regime()
    results = []
    for ticker in config.ALL_TICKERS:
        try:
            df_raw = fetcher.get_historical(ticker)
            if df_raw is None: continue
            df       = compute_indicators(df_raw)
            rs_data  = fetcher.get_relative_strength(ticker)
            earn_data= fetcher.get_earnings_date(ticker)
            score    = score_ticker(df, ticker, vix=vix_val, fg=fg_val,
                                    rs_data=rs_data, earnings_data=earn_data)
            sig      = generate_signal(df, score)
            price    = fetcher.get_current_price(ticker)
            last     = df.iloc[-1]
            results.append({
                "ticker":      ticker,
                "signal":      score["signal"],
                "score":       score["score"],
                "setup_type":  score.get("setup_type", "MIXED"),
                "price_eur":   price["price_eur"]  if price else 0,
                "price_usd":   price["price_usd"]  if price else 0,
                "change_pct":  price["change_pct"] if price else 0,
                "entry_eur":   sig.get("entry_eur",     0),
                "sl_eur":      sig.get("stop_loss_eur", 0),
                "target_eur":  sig.get("target_eur",    0),
                "rr":          sig.get("risk_reward",   0),
                "shares":      sig.get("shares",        0),
                "rsi":         round(float(last.get("RSI",      50)), 1),
                "macd_hist":   round(float(last.get("MACD_hist", 0)), 3),
                "rs":          rs_data.get("rs", 0),
                "earnings_warn": earn_data.get("warning", False),
                "earnings_level": earn_data.get("level", "none"),
                "earnings_date":  earn_data.get("date", None),
                "reason":      score.get("explanation", "")[:80],
                "block":       score.get("block_reason", ""),
            })
        except Exception as e:
            print(f"[Scan] Errore {ticker}: {e}")
    results.sort(key=lambda x: x["score"], reverse=True)
    return jsonify(sanitize(results))


@app.route("/api/backtest/<ticker>")
def backtest(ticker):
    ticker = ticker.upper().strip()
    try:
        df_raw = fetcher.get_historical(ticker)
        if df_raw is None:
            return jsonify({"error": "Dati non disponibili"}), 404
        bt     = Backtester(df_raw, ticker)
        result = bt.run()
        result["trades"] = result.get("trades", [])[-20:]
        return jsonify(sanitize(result))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/market")
def market():
    return jsonify(sanitize({
        "vix":        news_a.get_vix(),
        "fear_greed": news_a.get_fear_greed(),
        "eur_usd":    fetcher.eur_usd,
    }))


@app.route("/api/ai/<ticker>")
def ai_analyze(ticker):
    """
    Analisi AI Groq — chiamata separata (on-demand) per non rallentare il caricamento.
    Riceve tutti i dati già calcolati e chiede a llama-3.3-70b un verdetto ragionato.
    """
    ticker = ticker.upper().strip()
    try:
        df_raw = fetcher.get_historical(ticker)
        if df_raw is None:
            return jsonify({"error": "Dati non disponibili"}), 404

        df            = compute_indicators(df_raw)
        vix_val, fg_val = _get_regime()
        rs_data       = fetcher.get_relative_strength(ticker)
        earnings_data = fetcher.get_earnings_date(ticker)
        mtf_data      = fetcher.get_multitimeframe(ticker)
        sent          = news_a.get_full_sentiment(ticker)

        score = score_ticker(df, ticker, vix=vix_val, fg=fg_val,
                             rs_data=rs_data, earnings_data=earnings_data)
        mtf_adj = _mtf_score_adjustment(mtf_data)
        if mtf_adj != 0:
            score["score"] = round(min(max(score["score"] + mtf_adj, 0), 100), 1)

        sig = generate_signal(df, score)

        # Costruisci testo progressione score per il prompt
        steps_text = ""
        for step in score.get("score_steps", []):
            d = f"({step['delta']:+.1f})" if step.get("delta") is not None else ""
            steps_text += f"  {step['label']}: {step['value']}/100 {d}" + "\n"

        # Arricchisci il dict signal con i dati extra per il prompt
        sig["mtf_summary"]    = f"{mtf_data.get('alignment','N/A')} — {mtf_data.get('bullish_count',0)}/{mtf_data.get('total_tf',3)} timeframe bullish"
        sig["rs_info"]        = f"{rs_data.get('label','N/A')} ({rs_data.get('rs',0):+.2f}% vs SP500 in {rs_data.get('days',20)} giorni)"
        sig["earn_info"]      = earnings_data.get("label", "N/A")
        sig["setup_type"]     = score.get("setup_type", "MIXED")
        sig["score_steps_text"] = steps_text.strip()

        analysis = ai_analyst.analyze(sig, sent)
        return jsonify({"analysis": analysis, "ticker": ticker})

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────

@app.route("/api/backtest_all")
def backtest_all():
    """
    Esegue backtest su tutta la watchlist e ritorna statistiche
    aggregate per ticker, per settore e totali.
    """
    results_by_ticker = {}
    
    for ticker in config.ALL_TICKERS:
        try:
            df_raw = fetcher.get_historical(ticker)
            if df_raw is None:
                continue
            bt     = Backtester(df_raw, ticker)
            result = bt.run()
            result["trades"] = result.get("trades", [])
            results_by_ticker[ticker] = result
        except Exception as e:
            print(f"[BacktestAll] Errore {ticker}: {e}")
            results_by_ticker[ticker] = {"error": str(e), "ticker": ticker}

    # ── Statistiche per settore ────────────────────────────────────────
    sector_stats = {}
    for sector, tickers in config.WATCHLIST.items():
        sector_trades  = []
        sector_capital = 0
        for t in tickers:
            r = results_by_ticker.get(t)
            if not r or "error" in r:
                continue
            sector_trades.extend(r.get("trades", []))
            sector_capital += r.get("total_return", 0)

        wins  = [t for t in sector_trades if t.get("win")]
        total = len(sector_trades)
        sector_stats[sector] = {
            "tickers":       tickers,
            "total_trades":  total,
            "wins":          len(wins),
            "win_rate":      round(len(wins) / total * 100, 1) if total else 0,
            "avg_return_pct": round(sector_capital / len([t for t in tickers
                              if t in results_by_ticker and "error" not in results_by_ticker[t]])
                              , 2) if tickers else 0,
            "total_pnl_eur": round(sum(t.get("pnl_eur", 0) for t in sector_trades), 2),
        }

    # ── Statistiche aggregate totali ──────────────────────────────────
    all_trades   = []
    total_return = 0
    valid_tickers = 0
    for r in results_by_ticker.values():
        if "error" in r:
            continue
        all_trades.extend(r.get("trades", []))
        total_return += r.get("total_return", 0)
        valid_tickers += 1

    all_wins  = [t for t in all_trades if t.get("win")]
    total_pnl = sum(t.get("pnl_eur", 0) for t in all_trades)
    gross_win = sum(t.get("pnl_eur", 0) for t in all_trades if t.get("pnl_eur", 0) > 0)
    gross_loss= abs(sum(t.get("pnl_eur", 0) for t in all_trades if t.get("pnl_eur", 0) < 0))

    # Distribuzione exit type
    exit_types = {}
    for t in all_trades:
        et = t.get("exit_type", "OTHER")
        exit_types[et] = exit_types.get(et, 0) + 1

    aggregate = {
        "total_tickers":   valid_tickers,
        "total_trades":    len(all_trades),
        "total_wins":      len(all_wins),
        "win_rate":        round(len(all_wins) / len(all_trades) * 100, 1) if all_trades else 0,
        "total_pnl_eur":   round(total_pnl, 2),
        "profit_factor":   round(gross_win / gross_loss, 2) if gross_loss > 0 else 0,
        "avg_return_pct":  round(total_return / valid_tickers, 2) if valid_tickers else 0,
        "avg_pnl_per_trade": round(total_pnl / len(all_trades), 2) if all_trades else 0,
        "exit_types":      exit_types,
        "initial_capital": config.CAPITAL,
    }

    # Classifica ticker per rendimento
    ranking = sorted(
        [{"ticker": t, **r} for t, r in results_by_ticker.items() if "error" not in r],
        key=lambda x: x.get("total_return", -999),
        reverse=True
    )
    for r in ranking:
        r.pop("trades", None)   # troppo pesante per il JSON aggregato

    return jsonify(sanitize({
        "aggregate":    aggregate,
        "by_sector":    sector_stats,
        "by_ticker":    ranking,
        "errors":       {t: r["error"] for t, r in results_by_ticker.items() if "error" in r},
    }))


def _mtf_score_adjustment(mtf: dict) -> int:
    """
    Declassa lo score se i timeframe sono in conflitto.
    Penalità ridotte: il daily è il timeframe operativo principale.
    Weekly bearish + daily bullish = -7 (non -15: il daily conta di più)
    """
    if not mtf or "weekly" not in mtf or "daily" not in mtf:
        return 0

    w = mtf.get("weekly", {})
    d = mtf.get("daily",  {})
    h = mtf.get("h4",     {})

    if "error" in w or "error" in d:
        return 0

    w_bull = "bull" in w.get("trend", "")
    d_bull = "bull" in d.get("trend", "")
    h_bull = "bull" in h.get("trend", "") if "error" not in h else d_bull

    if w_bull and d_bull and h_bull:
        return +8    # allineamento totale: bonus
    if w_bull and d_bull:
        return +4    # quasi allineati
    if not w_bull and d_bull and h_bull:
        return -5    # daily+4H bullish ma weekly no: segnale valido ma cauto
    if not w_bull and d_bull:
        return -7    # conflitto principale: penalità moderata
    if not w_bull and not d_bull and h_bull:
        return -8    # solo 4H bullish: rimbalzo in downtrend
    if not w_bull and not d_bull:
        return -10   # tutto bearish: penalità ma non letale
    return 0


def _get_chart_data(df, n=90):
    tail = df.tail(n)
    return {
        "dates":     [d.strftime("%Y-%m-%d") for d in tail.index],
        "close":     [round(float(v), 2) for v in tail["Close"]],
        "volume":    [int(v) for v in tail["Volume"]],
        "bb_upper":  [round(float(v), 2) for v in tail["BB_upper"]],
        "bb_lower":  [round(float(v), 2) for v in tail["BB_lower"]],
        "bb_mid":    [round(float(v), 2) for v in tail["BB_mid"]],
        "ma20":      [round(float(v), 2) for v in tail["MA20"]],
        "ma50":      [round(float(v), 2) for v in tail["MA50"]],
        "rsi":       [round(float(v), 1) for v in tail["RSI"]],
        "macd":      [round(float(v), 3) for v in tail["MACD"]],
        "macd_sig":  [round(float(v), 3) for v in tail["MACD_signal"]],
        "macd_hist": [round(float(v), 3) for v in tail["MACD_hist"]],
    }


if __name__ == "__main__":
    print(f"\n🚀 SwingTool v3 — http://{config.FLASK_HOST}:{config.FLASK_PORT}")
    print(f"   Capitale: €{config.CAPITAL} | {len(config.ALL_TICKERS)} ticker | EUR/USD {fetcher.eur_usd:.4f}\n")
    app.run(host=config.FLASK_HOST, port=config.FLASK_PORT, debug=config.FLASK_DEBUG)
