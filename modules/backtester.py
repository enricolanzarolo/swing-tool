# modules/backtester.py — Modulo 7: Backtesting Engine
# Simula il nostro algoritmo sugli ultimi 2 anni di dati storici
# Calcola: win rate, rendimento, max drawdown, operazioni simulate

import pandas as pd
import numpy as np
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from modules.indicators import compute_indicators
from modules.scorer    import Scorer

# ─────────────────────────────────────────────────────────────────────────────
# COSTANTI
# ─────────────────────────────────────────────────────────────────────────────

COMMISSION_USD    = config.TRADE_COMMISSION * config.EUR_USD_DEFAULT  # ~€1 in USD
MIN_BARS_WARMUP   = 60    # candele minime prima di iniziare a segnalare
MAX_HOLD_BARS     = config.HOLDING_DAYS_MAX
SL_MULTIPLIER     = config.ATR_STOP_MULTIPLIER
TARGET_MULTIPLIER = config.ATR_TARGET_MULTIPLIER

# ─────────────────────────────────────────────────────────────────────────────
# CLASSE BACKTESTER
# ─────────────────────────────────────────────────────────────────────────────

class Backtester:
    """
    Simula l'algoritmo su dati storici.
    Per ogni giorno nel passato:
      1. Calcola indicatori e score (come farebbe il tool oggi)
      2. Se score >= BUY_THRESHOLD → simula un acquisto
      3. Gestisce stop loss, target e scadenza temporale
      4. Registra ogni trade e calcola statistiche
    """

    def __init__(self, df_raw: pd.DataFrame, ticker: str = ""):
        self.ticker  = ticker
        self.df_raw  = df_raw
        self.trades  = []   # lista di tutti i trade simulati
        self.equity  = []   # curva del capitale nel tempo

    def run(self) -> dict:
        """Esegui il backtest completo. Ritorna dict con statistiche."""

        df_full = compute_indicators(self.df_raw)

        if len(df_full) < MIN_BARS_WARMUP + 20:
            return {"error": f"Dati insufficienti per {self.ticker}"}

        capital       = config.CAPITAL
        peak_capital  = capital
        max_drawdown  = 0.0
        in_trade      = False
        trade_entry    = {}
        self._block_counts = {}  # diagnostica: perché i segnali vengono bloccati

        # Scorre ogni candela dal warmup in poi
        for i in range(MIN_BARS_WARMUP, len(df_full)):

            # ── Dati disponibili FINO a questa candela (no lookahead!) ────
            df_slice = df_full.iloc[:i+1].copy()
            row      = df_slice.iloc[-1]
            date     = df_full.index[i]

            close    = float(row["Close"])
            atr      = float(row.get("ATR", close * 0.02))
            high     = float(row["High"])
            low      = float(row["Low"])

            # ── Gestisci trade aperto ─────────────────────────────────────
            if in_trade:
                days_held = (date - trade_entry["date"]).days

                hit_sl     = low  <= trade_entry["sl"]
                hit_target = high >= trade_entry["target"]
                expired    = days_held >= MAX_HOLD_BARS

                if hit_target and hit_sl:
                    # Entrambi toccati: usa l'ordine che appare prima
                    # Per semplicità: se apre sopra SL e sotto target → target
                    exit_price = trade_entry["target"]
                    exit_type  = "TARGET"
                elif hit_target:
                    exit_price = trade_entry["target"]
                    exit_type  = "TARGET"
                elif hit_sl:
                    exit_price = trade_entry["sl"]
                    exit_type  = "STOP_LOSS"
                elif expired:
                    exit_price = close
                    exit_type  = "EXPIRED"
                else:
                    # Trade ancora aperto
                    self.equity.append({"date": date, "capital": capital})
                    continue

                # Calcola P&L
                shares   = trade_entry["shares"]
                pnl_usd  = (exit_price - trade_entry["entry"]) * shares
                pnl_usd -= COMMISSION_USD * 2   # buy + sell
                pnl_eur  = pnl_usd / config.EUR_USD_DEFAULT

                capital    += pnl_eur
                in_trade    = False

                # Registra trade
                self.trades.append({
                    "ticker":      self.ticker,
                    "entry_date":  trade_entry["date"].strftime("%Y-%m-%d"),
                    "exit_date":   date.strftime("%Y-%m-%d"),
                    "days_held":   days_held,
                    "entry_usd":   round(trade_entry["entry"], 2),
                    "exit_usd":    round(exit_price, 2),
                    "sl_usd":      round(trade_entry["sl"], 2),
                    "target_usd":  round(trade_entry["target"], 2),
                    "shares":      shares,
                    "pnl_eur":     round(pnl_eur, 2),
                    "pnl_pct":     round(pnl_usd / (trade_entry["entry"] * shares) * 100, 2),
                    "exit_type":   exit_type,
                    "score":       trade_entry["score"],
                    "size_factor": trade_entry.get("size_factor", 1.0),
                    "win":         pnl_eur > 0,
                })

                # Aggiorna drawdown
                if capital > peak_capital:
                    peak_capital = capital
                dd = (peak_capital - capital) / peak_capital * 100
                if dd > max_drawdown:
                    max_drawdown = dd

                self.equity.append({"date": date, "capital": capital})
                continue

            # ── Cerca nuovo segnale (candela N) ──────────────────────────
            # FIX look-ahead bias: il segnale viene calcolato sulla candela N
            # ma l'entry avviene al prezzo di APERTURA della candela N+1
            # (nella realtà: vedi il segnale a mercati chiusi, entri il giorno dopo)
            scorer = Scorer(df_slice, self.ticker)
            scorer.vix_value = 20   # condizioni neutre — no penalità regime attuale
            scorer.fg_value  = 50
            scorer.rs_data   = {}
            scorer.earnings_data = {}
            score_result = scorer.compute()
            score        = score_result["score"]
            signal       = score_result["signal"]
            breakdown    = score_result.get("breakdown", {})

            # FIX 2: Filtro ATR percentile — trada solo quando il titolo
            # ha volatilità sufficiente (ATR percentile > 45)
            # Esclude i periodi di laterale compresso dove i segnali sono rumore
            atr_pct_rank = 50  # default neutro
            if "atr_rr" in breakdown:
                reason_str = breakdown["atr_rr"].get("reason", "")
                # estrai percentile dalla stringa "RR=1.4:1 | ATR 62°pct"
                try:
                    pct_part = reason_str.split("ATR ")[1].split("°")[0]
                    atr_pct_rank = float(pct_part)
                except Exception:
                    pass

            if signal == "BUY" and atr_pct_rank < 45:
                signal = "WATCH"  # volatilità insufficiente
                self._block_counts["ATR percentile basso (<45)"] =                     self._block_counts.get("ATR percentile basso (<45)", 0) + 1

            # FIX 3: Weekly trend check — non entrare contro il trend settimanale
            # Override: se RSI < 40 (oversold profondo) il pullback è già scontato
            # e il segnale è un rimbalzo valido anche in downtrend strutturale
            rsi_now = float(score_result.get("breakdown", {}).get("mr", {}).get("detail", "RSI=50").split("RSI=")[1].split(",")[0]) if "mr" in score_result.get("breakdown", {}) else 50
            if signal == "BUY" and len(df_slice) >= 10 and rsi_now >= 40:
                weekly_close = df_slice["Close"].resample("W").last().dropna()
                if len(weekly_close) >= 10:
                    ema10w = weekly_close.ewm(span=10).mean().iloc[-1]
                    ema20w = weekly_close.ewm(span=20).mean().iloc[-1]
                    price_w = weekly_close.iloc[-1]
                    if price_w < ema10w and price_w < ema20w and ema10w < ema20w:
                        signal = "WATCH"
                        self._block_counts["Weekly downtrend"] =                             self._block_counts.get("Weekly downtrend", 0) + 1

            # Diagnostica: traccia motivo non-BUY
            if signal != "BUY":
                hard_block = score_result.get("block_reason", "")
                if hard_block:
                    # Normalizza label ATR: tutti i percentili → stessa chiave
                    if "ATR percentile basso" in hard_block:
                        key = "ATR percentile basso (<30°)"
                    else:
                        key = hard_block[:45]
                elif score < config.SIGNAL_BUY_THRESHOLD:
                    key = f"score_basso_{int(score//10)*10}-{int(score//10)*10+9}"
                else:
                    key = "filtro_post_score"
                self._block_counts[key] = self._block_counts.get(key, 0) + 1
                self.equity.append({"date": date, "capital": capital})
                continue

            # ── Entry al giorno DOPO (FIX look-ahead bias) ───────────────
            # Verifica che esista la candela N+1
            if i + 1 >= len(df_full):
                self.equity.append({"date": date, "capital": capital})
                continue

            next_row   = df_full.iloc[i + 1]
            entry      = float(next_row["Open"])   # prezzo apertura giorno dopo
            entry_date = df_full.index[i + 1]
            entry_atr  = float(next_row.get("ATR", entry * 0.02))

            sl     = entry - entry_atr * SL_MULTIPLIER
            target = entry + entry_atr * TARGET_MULTIPLIER

            # Sicurezza: sl max 6% sotto entry
            sl     = max(sl,     entry * 0.94)
            sl     = min(sl,     entry * 0.995)
            target = max(target, entry * 1.01)

            # Position sizing adattivo: rischio 2% del capitale (o 1% se setup esaurito)
            size_factor     = score_result.get("size_factor", 1.0)
            risk_eur        = capital * config.MAX_RISK_PER_TRADE * size_factor
            risk_usd        = risk_eur * config.EUR_USD_DEFAULT
            risk_per_share  = entry - sl
            if risk_per_share <= 0:
                self.equity.append({"date": date, "capital": capital})
                continue

            shares = max(1, int(risk_usd / risk_per_share))
            cost   = shares * entry / config.EUR_USD_DEFAULT + config.TRADE_COMMISSION
            if cost > capital:
                shares = max(1, int((capital - config.TRADE_COMMISSION) *
                                    config.EUR_USD_DEFAULT / entry))
            if size_factor < 1.0:
                self._block_counts["size_ridotta_50pct"] =                     self._block_counts.get("size_ridotta_50pct", 0) + 1

            in_trade    = True
            trade_entry = {
                "date":        entry_date,
                "entry":       entry,
                "sl":          sl,
                "target":      target,
                "shares":      shares,
                "score":       score,
                "size_factor": score_result.get("size_factor", 1.0),
                "signal_date": date,
            }

            self.equity.append({"date": date, "capital": capital})

        # ── Chiudi eventuale trade aperto a fine dati ─────────────────────
        if in_trade:
            last_row   = df_full.iloc[-1]
            last_close = float(last_row["Close"])
            shares     = trade_entry["shares"]
            pnl_usd    = (last_close - trade_entry["entry"]) * shares - COMMISSION_USD * 2
            pnl_eur    = pnl_usd / config.EUR_USD_DEFAULT
            capital   += pnl_eur
            self.trades.append({
                "ticker":      self.ticker,
                "entry_date":  trade_entry["date"].strftime("%Y-%m-%d"),
                "exit_date":   df_full.index[-1].strftime("%Y-%m-%d"),
                "days_held":   (df_full.index[-1] - trade_entry["date"]).days,
                "entry_usd":   round(trade_entry["entry"], 2),
                "exit_usd":    round(last_close, 2),
                "sl_usd":      round(trade_entry["sl"], 2),
                "target_usd":  round(trade_entry["target"], 2),
                "shares":      shares,
                "pnl_eur":     round(pnl_eur, 2),
                "pnl_pct":     round(pnl_usd / (trade_entry["entry"] * shares) * 100, 2),
                "exit_type":   "OPEN_AT_END",
                "score":       trade_entry["score"],
                "win":         pnl_eur > 0,
            })

        return self._calc_stats(capital, max_drawdown)

    # ─────────────────────────────────────────
    # STATISTICHE
    # ─────────────────────────────────────────

    def _calc_stats(self, final_capital: float, max_drawdown: float) -> dict:
        trades = self.trades
        n      = len(trades)

        if n == 0:
            return {
                "ticker":         self.ticker,
                "total_trades":   0,
                "win_rate":       0,
                "total_return":   0,
                "max_drawdown":   0,
                "avg_pnl":        0,
                "best_trade":     0,
                "worst_trade":    0,
                "avg_days_held":  0,
                "profit_factor":  0,
                "final_capital":  config.CAPITAL,
                "trades":         [],
                "error":          "Nessun segnale BUY generato nel periodo",
            }

        wins         = [t for t in trades if t["win"]]
        losses       = [t for t in trades if not t["win"]]
        win_rate     = len(wins) / n * 100
        total_return = (final_capital - config.CAPITAL) / config.CAPITAL * 100
        avg_pnl      = sum(t["pnl_eur"] for t in trades) / n
        best_trade   = max(t["pnl_eur"] for t in trades)
        worst_trade  = min(t["pnl_eur"] for t in trades)
        avg_days     = sum(t["days_held"] for t in trades) / n

        gross_profit = sum(t["pnl_eur"] for t in wins)   if wins   else 0
        gross_loss   = abs(sum(t["pnl_eur"] for t in losses)) if losses else 0.001
        profit_factor = gross_profit / gross_loss

        # Exit type breakdown
        exit_counts = {}
        for t in trades:
            k = t["exit_type"]
            exit_counts[k] = exit_counts.get(k, 0) + 1

        # Score medio dei trade vincenti vs perdenti
        avg_score_win  = sum(t["score"] for t in wins)   / len(wins)   if wins   else 0
        avg_score_loss = sum(t["score"] for t in losses) / len(losses) if losses else 0

        total_bars = max(len(self.df_raw) - MIN_BARS_WARMUP, 1)
        avg_trade_every = round(total_bars / n, 0) if n > 0 else 0
        signal_freq = f"1 trade ogni {avg_trade_every:.0f} giorni"

        return {
            "ticker":          self.ticker,
            "total_trades":    n,
            "win_rate":        round(win_rate, 1),
            "total_return":    round(total_return, 2),
            "max_drawdown":    round(max_drawdown, 2),
            "avg_pnl":         round(avg_pnl, 2),
            "best_trade":      round(best_trade, 2),
            "worst_trade":     round(worst_trade, 2),
            "avg_days_held":   round(avg_days, 1),
            "profit_factor":   round(profit_factor, 2),
            "final_capital":   round(final_capital, 2),
            "initial_capital": config.CAPITAL,
            "exit_counts":     exit_counts,
            "avg_score_win":   round(avg_score_win, 1),
            "avg_score_loss":  round(avg_score_loss, 1),
            "signal_frequency":   signal_freq,
            "buy_threshold_used": config.SIGNAL_BUY_THRESHOLD,
            "signal_stats":       self._block_counts,
            "trades":             trades,
        }


# ─────────────────────────────────────────────────────────────────────────────
# BACKTEST SU INTERA WATCHLIST
# ─────────────────────────────────────────────────────────────────────────────

def run_backtest_all(fetcher) -> list:
    """Esegue backtest su tutti i ticker e ritorna lista ordinata per rendimento."""
    from modules.data_fetcher import DataFetcher

    results = []
    tickers = config.ALL_TICKERS

    print(f"\n[Backtester] Avvio backtest su {len(tickers)} ticker ({config.SWING_PERIOD_DAYS} giorni)...")

    for i, ticker in enumerate(tickers, 1):
        print(f"  [{i:2}/{len(tickers)}] {ticker:<6}...", end=" ", flush=True)
        df_raw = fetcher.get_historical(ticker)

        if df_raw is None or len(df_raw) < 100:
            print("⚠️  dati insufficienti")
            continue

        bt     = Backtester(df_raw, ticker)
        result = bt.run()

        if "error" not in result or result.get("total_trades", 0) > 0:
            results.append(result)
            wr = result.get("win_rate", 0)
            tr = result.get("total_return", 0)
            n  = result.get("total_trades", 0)
            print(f"✓  {n:2} trade | WR: {wr:.0f}% | Return: {tr:+.1f}%")
        else:
            print(f"⚠️  {result.get('error', 'nessun trade')}")

    results.sort(key=lambda x: x.get("total_return", -999), reverse=True)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# STAMPA RISULTATI
# ─────────────────────────────────────────────────────────────────────────────

def print_backtest(r: dict):
    """Stampa risultati dettagliati di un backtest."""
    if "error" in r and r.get("total_trades", 0) == 0:
        print(f"\n  ⚠️  {r['ticker']}: {r['error']}")
        return

    icon = "🟢" if r["total_return"] > 0 else "🔴"
    print(f"\n{'═'*58}")
    print(f"  {icon} {r['ticker']:<6}  Backtest 2 anni")
    print(f"{'═'*58}")
    print(f"  Capitale iniziale  : €{r['initial_capital']:.0f}")
    print(f"  Capitale finale    : €{r['final_capital']:.2f}")
    print(f"  Rendimento totale  : {r['total_return']:+.2f}%")
    print(f"  Max Drawdown       : -{r['max_drawdown']:.2f}%")
    print(f"{'─'*58}")
    print(f"  Totale trade       : {r['total_trades']}")
    print(f"  Win Rate           : {r['win_rate']:.1f}%")
    print(f"  Profit Factor      : {r['profit_factor']:.2f}  {'✅' if r['profit_factor'] > 1.3 else '⚠️'}")
    print(f"  P&L medio/trade    : €{r['avg_pnl']:+.2f}")
    print(f"  Miglior trade      : €{r['best_trade']:+.2f}")
    print(f"  Peggior trade      : €{r['worst_trade']:+.2f}")
    print(f"  Giorni medi/trade  : {r['avg_days_held']:.1f}")
    print(f"{'─'*58}")
    print(f"  Uscite:")
    for k, v in r.get("exit_counts", {}).items():
        pct = v / r["total_trades"] * 100
        print(f"    {k:<15}: {v:3} ({pct:.0f}%)")
    print(f"{'─'*58}")
    print(f"  Score medio (vincenti) : {r['avg_score_win']:.1f}")
    print(f"  Score medio (perdenti) : {r['avg_score_loss']:.1f}")

    # Ultimi 5 trade
    trades = r.get("trades", [])[-5:]
    if trades:
        print(f"\n  Ultimi {len(trades)} trade:")
        for t in trades:
            icon_t = "✅" if t["win"] else "❌"
            print(f"  {icon_t} {t['entry_date']} → {t['exit_date']}  "
                  f"${t['entry_usd']} → ${t['exit_usd']}  "
                  f"P&L: €{t['pnl_eur']:+.2f}  [{t['exit_type']}]")


# ─────────────────────────────────────────────────────────────────────────────
# TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from modules.data_fetcher import DataFetcher

    fetcher = DataFetcher()

    # Test su 4 ticker per velocità
    test_tickers = ["AAPL", "NVDA", "TSLA", "JPM"]

    print("\n" + "="*58)
    print("TEST Modulo 7 — Backtesting Engine")
    print(f"Periodo: {config.SWING_PERIOD_DAYS} giorni | "
          f"Capitale: €{config.CAPITAL} | "
          f"Rischio/trade: {config.MAX_RISK_PER_TRADE*100:.0f}%")
    print("="*58)

    all_results = []

    for ticker in test_tickers:
        print(f"\n[{ticker}] Scaricamento dati...", end=" ", flush=True)
        df_raw = fetcher.get_historical(ticker)
        if df_raw is None:
            print("❌ errore")
            continue
        print(f"{len(df_raw)} candele  |  Backtest in corso...", end=" ", flush=True)

        bt     = Backtester(df_raw, ticker)
        result = bt.run()
        all_results.append(result)
        print("✓")
        print_backtest(result)

    # ── Riepilogo comparativo ──────────────────────────────────────────────
    print(f"\n\n{'═'*58}")
    print("📊 RIEPILOGO COMPARATIVO")
    print("="*58)
    print(f"  {'Ticker':<8} {'Trade':>6} {'Win%':>6} {'Return':>8} {'MaxDD':>8} {'PF':>6}")
    print(f"  {'─'*50}")

    valid = [r for r in all_results if r.get("total_trades", 0) > 0]
    valid.sort(key=lambda x: x["total_return"], reverse=True)

    for r in valid:
        icon = "🟢" if r["total_return"] > 0 else "🔴"
        print(f"  {icon} {r['ticker']:<6} "
              f"{r['total_trades']:>6} "
              f"{r['win_rate']:>5.1f}% "
              f"{r['total_return']:>+7.2f}% "
              f"{r['max_drawdown']:>7.2f}% "
              f"{r['profit_factor']:>6.2f}")

    if valid:
        avg_wr  = sum(r["win_rate"]     for r in valid) / len(valid)
        avg_ret = sum(r["total_return"] for r in valid) / len(valid)
        print(f"\n  Media  {'':>6} {'':>6} {avg_wr:>5.1f}% {avg_ret:>+7.2f}%")
        best = max(valid, key=lambda x: x["total_return"])
        print(f"\n  🏆 Miglior ticker: {best['ticker']}  "
              f"({best['total_return']:+.2f}%  |  WR {best['win_rate']:.0f}%)")

    print(f"\n✅ Modulo 7 completato!")
