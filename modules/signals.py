# modules/signals.py — Modulo 4: Segnali Completi di Trading
# Genera entry, stop loss, target, position sizing, tempo stimato
# Per ogni segnale BUY calcola tutto il necessario per aprire la posizione

import pandas as pd
import numpy as np
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

# ─────────────────────────────────────────────────────────────────────────────
# CLASSE SIGNAL GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

class SignalGenerator:
    """
    Prende il DataFrame con indicatori e il risultato dello scorer.
    Produce un segnale completo e actionable con tutti i numeri per Trade Republic.
    """

    def __init__(self, df: pd.DataFrame, score_result: dict):
        self.df     = df
        self.row    = df.iloc[-1]
        self.result = score_result
        self.ticker = score_result.get("ticker", "")

    def generate(self) -> dict:
        """Genera il segnale completo."""

        signal  = self.result["signal"]
        score   = self.result["score"]
        close   = float(self.row["Close"])
        atr     = float(self.row["ATR"])
        eur_usd = config.EUR_USD_DEFAULT  # verrà sovrascritto se passato

        # Prezzi di entry, SL, target in USD
        entry_usd  = self._calc_entry(close, atr)
        sl_usd     = self._calc_stop_loss(entry_usd, atr)
        target_usd = self._calc_target(entry_usd, atr)

        # Conversione in EUR
        entry_eur  = round(entry_usd  / config.EUR_USD_DEFAULT, 2)
        sl_eur     = round(sl_usd     / config.EUR_USD_DEFAULT, 2)
        target_eur = round(target_usd / config.EUR_USD_DEFAULT, 2)

        # Position sizing adattivo (size_factor iniettato da main.py se setup esaurito)
        sizing     = self._calc_position_size(entry_usd, sl_usd,
                         size_factor=getattr(self, "size_factor", 1.0))

        # Risk/Reward reale
        rr         = self._calc_rr(entry_usd, sl_usd, target_usd)

        # Tempo stimato in posizione
        holding    = self._estimate_holding_days(atr, close)

        # Percentuale di movimento attesa
        pct_to_target = (target_usd - entry_usd) / entry_usd * 100
        pct_to_sl     = (entry_usd - sl_usd)     / entry_usd * 100

        # Qualità del segnale
        quality    = self._signal_quality(score, rr)

        # Motivo principale del segnale
        reason     = self._main_reason()

        return {
            # Identificazione
            "ticker":          self.ticker,
            "signal":          signal,
            "score":           score,
            "quality":         quality,

            # Prezzi USD
            "entry_usd":       round(entry_usd,  2),
            "stop_loss_usd":   round(sl_usd,      2),
            "target_usd":      round(target_usd,  2),

            # Prezzi EUR
            "entry_eur":       entry_eur,
            "stop_loss_eur":   sl_eur,
            "target_eur":      target_eur,

            # Movimenti percentuali
            "pct_to_target":   round(pct_to_target, 2),
            "pct_to_sl":       round(pct_to_sl,     2),

            # Position sizing
            "shares":          sizing["shares"],
            "invested_eur":    sizing["invested_eur"],
            "invested_usd":    sizing["invested_usd"],
            "max_loss_eur":    sizing["max_loss_eur"],
            "capital_pct":     sizing["capital_pct"],

            # Metriche
            "risk_reward":     round(rr, 2),
            "holding_days":    holding,
            "atr_usd":         round(atr, 2),

            # Testo
            "reason":          reason,
            "breakdown":       self.result["breakdown"],
            "setup_type":      self.result.get("setup_type", "MIXED"),
            "block_reason":    self.result.get("block_reason", ""),

            # Livelli chiave e pattern
            "key_levels":      self._key_levels(close),
            "candle_pattern":  self._candle_pattern(),
        }

    # ─────────────────────────────────────────
    # CALCOLO ENTRY
    # Leggermente sotto il close per migliorare RR
    # Se il prezzo è in area oversold entriamo subito
    # ─────────────────────────────────────────
    def _calc_entry(self, close: float, atr: float) -> float:
        rsi      = float(self.row.get("RSI", 50))
        bb_pos   = float(self.row.get("BB_position", 0.5))
        bb_lower = float(self.row.get("BB_lower", close))

        # Se molto oversold o vicino alla banda: entry immediata sul close
        if rsi < config.RSI_OVERSOLD or bb_pos < 0.15:
            return close

        # Se MACD bullish cross appena avvenuto: entry immediata
        if int(self.row.get("MACD_cross", 0)) == 1:
            return close

        # Altrimenti: entry leggermente sotto con limit order (0.3% sotto close)
        # Questo migliora il RR senza rischiare di perdere il trade
        entry = close * 0.997
        # Non scendere sotto il BB_lower
        entry = max(entry, bb_lower * 1.005)
        return round(entry, 4)

    # ─────────────────────────────────────────
    # CALCOLO STOP LOSS
    # Basato su ATR per adattarsi alla volatilità del titolo
    # ─────────────────────────────────────────
    def _calc_stop_loss(self, entry: float, atr: float) -> float:
        bb_lower = float(self.row.get("BB_lower", entry))

        # Stop = entry - (ATR × moltiplicatore)
        sl_atr   = entry - atr * config.ATR_STOP_MULTIPLIER

        # Stop non può essere sotto il BB_lower - 0.5 ATR (supporto tecnico)
        sl_floor = bb_lower - atr * 0.5

        # Prendi il più alto tra i due (stop meno aggressivo)
        sl = max(sl_atr, sl_floor)

        # Stop massimo: mai più del 6% sotto l'entry (limite assoluto)
        sl_max_loss = entry * 0.94
        sl = max(sl, sl_max_loss)

        return round(sl, 4)

    # ─────────────────────────────────────────
    # CALCOLO TARGET
    # Target primario: BB_upper o ATR × moltiplicatore
    # ─────────────────────────────────────────
    def _calc_target(self, entry: float, atr: float) -> float:
        bb_upper = float(self.row.get("BB_upper", entry))
        ma50     = float(self.row.get("MA50", entry))

        # Target ATR
        tgt_atr  = entry + atr * config.ATR_TARGET_MULTIPLIER

        # Target BB_upper (resistenza naturale)
        tgt_bb   = bb_upper * 0.99  # leggermente sotto per realizzare prima

        # Target MA50 (se sopra il prezzo, è una resistenza)
        tgt_ma   = ma50 if ma50 > entry * 1.01 else None

        # Prendi il più conservativo tra ATR e BB_upper
        candidates = [tgt_atr, tgt_bb]
        if tgt_ma:
            candidates.append(tgt_ma)

        # Target = il più basso tra quelli > entry (più realistico)
        valid = [t for t in candidates if t > entry * 1.005]
        if valid:
            target = min(valid)
        else:
            target = entry + atr * 2  # fallback

        return round(target, 4)

    # ─────────────────────────────────────────
    # POSITION SIZING
    # Regola del 2%: non perdere più del 2% del capitale per trade
    # ─────────────────────────────────────────
    def _calc_position_size(self, entry_usd: float, sl_usd: float,
                            size_factor: float = 1.0) -> dict:
        capital_eur     = config.CAPITAL
        # size_factor < 1.0 quando setup è esaurito (RSI/BB overbought)
        # riduce il rischio massimo proporzionalmente (es: 1% invece di 2%)
        max_loss_eur    = capital_eur * config.MAX_RISK_PER_TRADE * size_factor

        risk_per_share_usd = entry_usd - sl_usd
        if risk_per_share_usd <= 0:
            risk_per_share_usd = entry_usd * 0.03  # fallback 3%

        # Converti risk in EUR
        risk_per_share_eur = risk_per_share_usd / config.EUR_USD_DEFAULT

        # Quante azioni possiamo comprare rispettando il rischio max?
        if risk_per_share_eur > 0:
            shares = int(max_loss_eur / risk_per_share_eur)
        else:
            shares = 0

        # Non investire più del 30% del capitale in un singolo trade
        max_shares_by_capital = int((capital_eur * 0.30) / (entry_usd / config.EUR_USD_DEFAULT))
        shares = min(shares, max_shares_by_capital)
        shares = max(shares, 1)  # almeno 1 azione

        # Calcoli finali
        entry_eur     = entry_usd / config.EUR_USD_DEFAULT
        invested_eur  = round(shares * entry_eur + config.TRADE_COMMISSION, 2)
        invested_usd  = round(shares * entry_usd, 2)
        actual_loss   = round(shares * risk_per_share_eur + config.TRADE_COMMISSION, 2)
        capital_pct   = round(invested_eur / capital_eur * 100, 1)

        return {
            "shares":       shares,
            "invested_eur": invested_eur,
            "invested_usd": invested_usd,
            "max_loss_eur": actual_loss,
            "capital_pct":  capital_pct,
        }

    # ─────────────────────────────────────────
    # RISK / REWARD
    # ─────────────────────────────────────────
    def _calc_rr(self, entry: float, sl: float, target: float) -> float:
        risk   = entry - sl
        reward = target - entry
        if risk <= 0:
            return 0
        return round(reward / risk, 2)

    # ─────────────────────────────────────────
    # STIMA GIORNI IN POSIZIONE
    # Basata su ATR: più alta la volatilità, prima raggiungiamo il target
    # ─────────────────────────────────────────
    def _estimate_holding_days(self, atr: float, close: float) -> dict:
        target_usd = float(self.row.get("BB_upper", close))
        entry_usd  = close

        distance   = abs(target_usd - entry_usd)
        if atr <= 0:
            atr = close * 0.02  # fallback 2%

        # Giorni = distanza / ATR giornaliero (con fattore di correzione 0.6
        # perché il prezzo non si muove linearmente ogni giorno)
        raw_days   = distance / atr / 0.6
        days_min   = max(int(raw_days * 0.5), config.HOLDING_DAYS_MIN)
        days_max   = min(int(raw_days * 1.8), config.HOLDING_DAYS_MAX)

        # Converti in settimane lavorative
        weeks_min  = round(days_min / 5, 1)
        weeks_max  = round(days_max / 5, 1)

        return {
            "days_min":  days_min,
            "days_max":  days_max,
            "weeks_min": weeks_min,
            "weeks_max": weeks_max,
            "label":     f"{days_min}-{days_max} giorni (~{weeks_min}-{weeks_max} settimane)",
        }

    # ─────────────────────────────────────────
    # LIVELLI CHIAVE
    # ─────────────────────────────────────────
    def _key_levels(self, close: float) -> dict:
        """Calcola i livelli chiave e la distanza % dal prezzo attuale."""
        row    = self.row
        df     = self.df
        result = {}

        def add(name, price):
            if price is not None and price > 0:
                dist_pct = round((float(price) - close) / close * 100, 2)
                result[name] = {"price": round(float(price), 2), "dist_pct": dist_pct}

        # Massimo e minimo degli ultimi 60 giorni
        tail60 = df.tail(60)
        add("recent_high", float(tail60["High"].max()))
        add("recent_low",  float(tail60["Low"].min()))

        # Medie mobili
        for ma in ["MA20", "MA50", "MA200"]:
            v = row.get(ma)
            if v is not None:
                add(ma.lower(), v)

        # Bollinger Bands
        add("bb_upper", row.get("BB_upper"))
        add("bb_lower", row.get("BB_lower"))

        # Swing points: resistenza/supporto piu vicini
        highs = df["High"].values
        lows  = df["Low"].values
        swing_highs, swing_lows = [], []
        for i in range(2, len(highs) - 2):
            if highs[i] == max(highs[i-2:i+3]):
                swing_highs.append(float(highs[i]))
            if lows[i] == min(lows[i-2:i+3]):
                swing_lows.append(float(lows[i]))

        res_above = [h for h in swing_highs if h > close * 1.005]
        if res_above:
            add("resistance", min(res_above))

        sup_below = [l for l in swing_lows if l < close * 0.995]
        if sup_below:
            add("support", max(sup_below))

        return result

    # ─────────────────────────────────────────
    # PATTERN CANDLESTICK
    # ─────────────────────────────────────────
    def _candle_pattern(self) -> str:
        """Identifica il pattern candlestick dell ultima barra."""
        if len(self.df) < 2:
            return "N/A"

        c  = self.row
        p  = self.df.iloc[-2]
        o, h, l, cl = float(c["Open"]), float(c["High"]), float(c["Low"]), float(c["Close"])
        po, ph, pl, pc = float(p["Open"]), float(p["High"]), float(p["Low"]), float(p["Close"])

        body      = abs(cl - o)
        candle_r  = h - l
        if candle_r == 0: return "N/A"
        upper_wick = h - max(cl, o)
        lower_wick = min(cl, o) - l
        body_pct   = body / candle_r

        if body_pct < 0.1:
            return "Doji (indecisione)"
        if lower_wick > body * 2 and upper_wick < body * 0.5 and cl > o:
            return "Hammer (segnale rialzista)"
        if upper_wick > body * 2 and lower_wick < body * 0.5 and cl < o:
            return "Shooting Star (segnale ribassista)"
        if cl > o and pc < po and cl > po and o < pc:
            return "Engulfing Rialzista"
        if cl < o and pc > po and cl < po and o > pc:
            return "Engulfing Ribassista"
        if cl > o and body_pct > 0.85:
            return "Marubozu Rialzista"
        if cl < o and body_pct > 0.85:
            return "Marubozu Ribassista"
        if h < ph and l > pl:
            return "Inside Bar (compressione)"
        return "Nessun pattern"

    # ─────────────────────────────────────────
    # QUALITA DEL SEGNALE
    # ─────────────────────────────────────────
    def _signal_quality(self, score: float, rr: float) -> str:
        """Qualità coerente con le soglie dello scorer (BUY>=55, WATCH>=35, SKIP<35)."""
        if score >= 70 and rr >= 2.0:  return "⭐⭐⭐ ECCELLENTE"
        if score >= 60 and rr >= 1.5:  return "⭐⭐ BUONO"
        if score >= 55:                return "⭐ ACCETTABILE"
        if score >= 35:                return "👁 WATCH"
        return                                "✗ SKIP"

    # ─────────────────────────────────────────
    # MOTIVO PRINCIPALE
    # ─────────────────────────────────────────
    def _main_reason(self) -> str:
        bd     = self.result.get("breakdown", {})
        strong = sorted(
            [(k, v) for k, v in bd.items() if v["score"] > 60],
            key=lambda x: x[1]["score"],
            reverse=True,
        )
        if strong:
            top = strong[0]
            return f"{top[0].upper()}: {top[1]['reason']}"
        return "Segnale debole — nessun indicatore dominante"


# ─────────────────────────────────────────────────────────────────────────────
# FUNZIONE RAPIDA
# ─────────────────────────────────────────────────────────────────────────────

def generate_signal(df: pd.DataFrame, score_result: dict) -> dict:
    gen = SignalGenerator(df, score_result)
    gen.size_factor = score_result.get("size_factor", 1.0)
    return gen.generate()


# ─────────────────────────────────────────────────────────────────────────────
# STAMPA SEGNALE FORMATTATA
# ─────────────────────────────────────────────────────────────────────────────

def print_signal(sig: dict):
    signal   = sig["signal"]
    icons    = {"BUY": "🟢", "WATCH": "🟡", "SKIP": "🔴"}
    icon     = icons.get(signal, "⚪")

    print(f"\n{'═'*58}")
    print(f"  {icon} {sig['ticker']:<6}  Score: {sig['score']}/100  {sig['quality']}")
    print(f"{'═'*58}")

    if signal == "BUY":
        print(f"\n  📋 SEGNALE D'ACQUISTO — {sig['ticker']}")
        print(f"  {'─'*50}")
        print(f"  Motivo principale : {sig['reason']}")
        print(f"\n  💰 PREZZI (USD)")
        print(f"     Entry          : ${sig['entry_usd']}")
        print(f"     Stop Loss      : ${sig['stop_loss_usd']}  (-{sig['pct_to_sl']}%)")
        print(f"     Target         : ${sig['target_usd']}  (+{sig['pct_to_target']}%)")
        print(f"     Risk/Reward    : {sig['risk_reward']}:1")

        print(f"\n  💶 PREZZI (EUR)")
        print(f"     Entry          : €{sig['entry_eur']}")
        print(f"     Stop Loss      : €{sig['stop_loss_eur']}")
        print(f"     Target         : €{sig['target_eur']}")

        print(f"\n  📊 POSITION SIZING (capitale €{config.CAPITAL})")
        print(f"     Azioni da comprare : {sig['shares']}")
        print(f"     Investimento       : €{sig['invested_eur']}  ({sig['capital_pct']}% capitale)")
        print(f"     Perdita massima    : €{sig['max_loss_eur']}  ({config.MAX_RISK_PER_TRADE*100:.0f}% rischio)")
        print(f"     Commissione TR     : €{config.TRADE_COMMISSION} (ingresso) + €{config.TRADE_COMMISSION} (uscita)")

        print(f"\n  ⏱  TEMPO STIMATO IN POSIZIONE")
        h = sig['holding_days']
        print(f"     {h['label']}")

        print(f"\n  📈 ISTRUZIONI PER TRADE REPUBLIC")
        print(f"     1. Cerca: {sig['ticker']}")
        print(f"     2. Ordine LIMIT a ${sig['entry_usd']} (€{sig['entry_eur']})")
        print(f"     3. Quantità: {sig['shares']} azioni")
        print(f"     4. Stop Loss: ${sig['stop_loss_usd']} (imposta subito dopo l'acquisto)")
        print(f"     5. Target:    ${sig['target_usd']} (ordine LIMIT di vendita)")

    elif signal == "WATCH":
        print(f"\n  👁  DA MONITORARE — {sig['ticker']}")
        print(f"  Score {sig['score']}/100 — mancano conferme per entrare")
        print(f"  Motivo: {sig['reason']}")
        bd = sig.get("breakdown", {})
        weak = [k for k, v in bd.items() if v["score"] < 40]
        if weak:
            print(f"  Indicatori da migliorare: {', '.join(w.upper() for w in weak)}")
    else:
        print(f"\n  ✗ SKIP — {sig['ticker']}")
        print(f"  Score {sig['score']}/100 — condizioni sfavorevoli")


# ─────────────────────────────────────────────────────────────────────────────
# TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from modules.data_fetcher import DataFetcher
    from indicators   import compute_indicators
    from scorer       import score_ticker

    fetcher = DataFetcher()

    # Aggiorna il tasso EUR/USD nel config
    config.EUR_USD_DEFAULT = fetcher.eur_usd

    tickers = ["AAPL", "NVDA", "MSFT", "TSLA", "AMD", "GOOGL", "JPM", "INTC"]
    signals = []

    print("\n" + "="*58)
    print("TEST Modulo 4 — Segnali completi")
    print("="*58)

    for ticker in tickers:
        df_raw = fetcher.get_historical(ticker)
        if df_raw is None:
            continue
        df     = compute_indicators(df_raw)
        scored = score_ticker(df, ticker)
        sig    = generate_signal(df, scored)
        signals.append(sig)

    # Stampa solo i BUY per primi, poi WATCH, poi SKIP
    for priority in ["BUY", "WATCH", "SKIP"]:
        group = [s for s in signals if s["signal"] == priority]
        for sig in sorted(group, key=lambda x: x["score"], reverse=True):
            print_signal(sig)

    # Riepilogo finale
    buys   = [s for s in signals if s["signal"] == "BUY"]
    watchs = [s for s in signals if s["signal"] == "WATCH"]
    skips  = [s for s in signals if s["signal"] == "SKIP"]

    print(f"\n\n{'═'*58}")
    print(f"📊 RIEPILOGO FINALE  ({len(signals)} ticker analizzati)")
    print(f"{'═'*58}")
    print(f"  🟢 BUY   : {len(buys)}")
    print(f"  🟡 WATCH : {len(watchs)}")
    print(f"  🔴 SKIP  : {len(skips)}")

    if buys:
        print(f"\n  💡 MIGLIORE OPPORTUNITÀ: {buys[0]['ticker']} — Score {buys[0]['score']}/100")
        print(f"     Entry: €{buys[0]['entry_eur']} | SL: €{buys[0]['stop_loss_eur']} | Target: €{buys[0]['target_eur']}")
        print(f"     {buys[0]['shares']} azioni × €{buys[0]['entry_eur']} = €{buys[0]['invested_eur']}")

    print(f"\n✅ Modulo 4 completato!")
