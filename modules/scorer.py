# modules/scorer.py — v3: pesi rivisti, fix bug RSI, filtri hard, regime mercato

import pandas as pd
import numpy as np
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

# ─────────────────────────────────────────────────────────────────────────────
# SCORER v3
# ─────────────────────────────────────────────────────────────────────────────

class Scorer:
    """
    Riceve il DataFrame completo con indicatori calcolati.
    Usa SEMPRE df.iloc[-1] come sorgente — nessun RSI doppio possibile.
    
    Pesi v2:  TREND 30% | MACD 25% | VOLUME 20% | ATR_RR 15% | MR 10%
    """

    def __init__(self, df: pd.DataFrame, ticker: str = ""):
        self.df     = df
        self.row    = df.iloc[-1]   # unica sorgente di verità
        self.ticker = ticker

    def compute(self) -> dict:

        # ── 1. Calcola score per categoria ───────────────────────────────
        breakdown = {
            "trend":  self._score_trend(),
            "macd":   self._score_macd(),
            "volume": self._score_volume(),
            "atr_rr": self._score_atr_rr(),
            "mr":     self._score_mean_reversion(),
        }

        # ── 2. Score pesato base ──────────────────────────────────────────
        raw_score = sum(
            breakdown[k]["score"] * config.WEIGHTS[k] / 100
            for k in breakdown
        )

        # ── 3. Filtri HARD — bloccano il segnale ──────────────────────────
        hard_block, block_reason = self._check_hard_filters()

        # ── 4. Regime di mercato ──────────────────────────────────────────
        regime_mult, regime_note = self._market_regime_multiplier()
        score = raw_score * regime_mult

        # ── 5. Score finale ───────────────────────────────────────────────
        score = round(min(max(score, 0), 100), 1)

        # ── 6. Setup type: trend following vs mean reversion ──────────────
        setup_type = self._classify_setup(breakdown)

        # ── 7. Segnale finale ─────────────────────────────────────────────
        if hard_block:
            signal = "SKIP"
            score  = min(score, 34)  # forza sotto soglia WATCH
        elif score >= config.SIGNAL_BUY_THRESHOLD:
            signal = "BUY"
        elif score >= config.SIGNAL_HOLD_THRESHOLD:
            signal = "WATCH"
        else:
            signal = "SKIP"

        # ── 8. Penalità Relative Strength vs SP500 ───────────────────────
        rs_data   = getattr(self, "rs_data",   None)
        rs_adj    = 0
        if rs_data and "rs" in rs_data:
            rs_val = rs_data["rs"]
            if   rs_val >= 5:   rs_adj = +8
            elif rs_val >= 2:   rs_adj = +4
            elif rs_val >= -2:  rs_adj = 0
            elif rs_val >= -5:  rs_adj = -4
            else:               rs_adj = -8
            score = round(min(max(score + rs_adj, 0), 100), 1)

        # ── 9. Penalità Earnings — logica 4 livelli ──────────────────────
        earnings   = getattr(self, "earnings_data", None)
        earn_pen   = False
        earn_label = ""
        earn_delta = 0

        if earnings and earnings.get("level", "none") != "none":
            level   = earnings.get("level", "none")
            penalty = earnings.get("penalty", 0)

            if level == "block":
                # Blocco totale: forza score sotto soglia BUY
                score      = min(score, config.SIGNAL_BUY_THRESHOLD - 1)
                signal     = "WATCH" if signal == "BUY" else signal
                earn_pen   = True
                earn_label = f"BLOCCATO — earnings tra {earnings.get('bdays_away','?')}gg"
                earn_delta = round(score - (score / (1 - 0)), 0)  # placeholder

            elif level == "high" and penalty > 0:
                pre_score  = score
                score      = round(score * (1 - penalty / 100), 1)
                earn_pen   = True
                earn_delta = round(score - pre_score, 1)
                earn_label = f"-{penalty}% (earnings tra {earnings.get('bdays_away','?')}gg)"
                if signal == "BUY" and score < config.SIGNAL_BUY_THRESHOLD:
                    signal = "WATCH"

            elif level == "medium" and penalty > 0:
                pre_score  = score
                score      = round(score * (1 - penalty / 100), 1)
                earn_pen   = True
                earn_delta = round(score - pre_score, 1)
                earn_label = f"-{penalty}% (earnings tra {earnings.get('bdays_away','?')}gg)"

        # ── 10. CAP PENALITÀ TOTALI ────────────────────────────────────────
        # Garantisce che le penalità cumulative non superino MAX_PENALTY_CAP
        # Evita che un titolo con score base 70 finisca a 40 per colpa di
        # moltiplicatori in cascata in mercati difficili
        max_pen = getattr(config, "MAX_PENALTY_CAP", 20)
        floor   = round(raw_score - max_pen, 1)
        if score < floor:
            score = round(max(floor, 0), 1)

        # ── 11. Penalità setup esaurito (RSI o BB overbought) ────────────
        # Indicator crowding: quando tutti gli indicatori sono estremi
        # il movimento è spesso già avanzato → score penalizzato + size ridotta
        rsi_val = float(self.row.get("RSI", 50))
        bb_pos  = float(self.row.get("BB_position", 0.5))
        overextended = (
            rsi_val > config.OVEREXTENDED_RSI_THRESHOLD or
            bb_pos  > config.OVEREXTENDED_BB_THRESHOLD
        )
        size_factor = 1.0
        overext_label = ""
        overext_delta = 0
        if overextended and signal == "BUY":
            pre_score     = score
            score         = round(score * config.OVEREXTENDED_SCORE_PENALTY, 1)
            overext_delta = round(score - pre_score, 1)
            size_factor   = config.OVEREXTENDED_SIZE_FACTOR
            parts = []
            if rsi_val > config.OVEREXTENDED_RSI_THRESHOLD:
                parts.append(f"RSI {rsi_val:.0f}")
            if bb_pos > config.OVEREXTENDED_BB_THRESHOLD:
                parts.append(f"BB {bb_pos:.0%}")
            overext_label = f"Setup esaurito ({', '.join(parts)}) → size ×0.5"
            if score < config.SIGNAL_BUY_THRESHOLD:
                signal = "WATCH"

        explanation = self._build_explanation(breakdown, score, signal,
                                               block_reason, regime_note, setup_type,
                                               rs_adj, earn_pen)

        # Costruisci progressione score leggibile
        score_steps = _build_score_steps(
            raw_score, regime_mult, rs_adj, earn_pen,
            getattr(self, "_mtf_adj", 0), score,
            earn_label=earn_label, earn_delta=earn_delta,
        )

        # Aggiorna score_steps con lo step overextended se presente
        if overextended and overext_delta != 0:
            score_steps.append({
                "label": overext_label,
                "value": round(score, 1),
                "delta": overext_delta,
            })

        return {
            "ticker":       self.ticker,
            "score":        score,
            "raw_score":    round(raw_score, 1),
            "signal":       signal,
            "setup_type":   setup_type,
            "hard_block":   hard_block,
            "block_reason": block_reason,
            "regime_note":  regime_note,
            "regime_mult":  regime_mult,
            "rs_adj":       rs_adj,
            "earn_penalty": earn_pen,
            "overextended": overextended,
            "size_factor":  size_factor,   # 0.5 se esaurito, 1.0 normale
            "score_steps":  score_steps,
            "breakdown":    breakdown,
            "explanation":  explanation,
        }

    # ─────────────────────────────────────────────────────
    # TREND  (peso 30%)
    #
    # Fix: ADX < 20 → score basso sempre (laterale ≠ bullish)
    # Fix: prezzo sotto MA20 + MA50 → score non può essere alto
    # ─────────────────────────────────────────────────────
    def _score_trend(self) -> dict:
        adx      = float(self.row.get("ADX",      0))
        di_plus  = float(self.row.get("DI_plus",  0))
        di_minus = float(self.row.get("DI_minus", 0))
        close    = float(self.row.get("Close",    1))
        ma20     = float(self.row.get("MA20",     close))
        ma50     = float(self.row.get("MA50",     close))
        ma200    = float(self.row.get("MA200",    close))

        above_ma20  = close > ma20
        above_ma50  = close > ma50
        above_ma200 = close > ma200

        # ── Forza del trend (ADX) ──────────────────────────────────────
        # ADX < 15 = mercato piatto → contributo vicino a 0
        # ADX 15-25 = debole → contributo parziale
        # ADX > 25 = trend presente
        # ADX > 40 = trend forte
        if adx < 15:
            adx_score = 10   # piatto = quasi neutro, non positivo
        elif adx < 20:
            adx_score = 20   # debole: non può essere BUY
        elif adx < 25:
            adx_score = 35
        elif adx < 35:
            adx_score = 65
        elif adx < 45:
            adx_score = 85
        else:
            adx_score = 95

        # ── Direzione del trend (DI) ───────────────────────────────────
        total_di = di_plus + di_minus
        if total_di > 0:
            di_ratio = di_plus / total_di   # 0=tutto bearish, 1=tutto bullish
        else:
            di_ratio = 0.5

        # Scala: di_ratio 0.5=neutro, 1.0=massimo bullish
        # Ma se ADX < 20 la direzione conta poco
        if adx < 20:
            di_score = 40 + (di_ratio - 0.5) * 20   # molto compresso
        else:
            di_score = 50 + (di_ratio - 0.5) * 100  # piena espansione

        # ── Posizione rispetto alle medie ──────────────────────────────
        ma_count_above = sum([above_ma20, above_ma50, above_ma200])
        ma_score = {0: 0, 1: 30, 2: 65, 3: 100}[ma_count_above]

        # ── Combinazione pesata ────────────────────────────────────────
        # ADX 40% | Direzione 35% | MA 25%
        combined = adx_score * 0.40 + di_score * 0.35 + ma_score * 0.25

        # ── Penalità critica: sotto MA20 E MA50 → cap a 40 ────────────
        # Prezzo sotto entrambe le medie di breve = non è un segnale BUY
        if not above_ma20 and not above_ma50:
            combined = min(combined, 40)

        # ── Penalità aggiuntiva: ADX < 20 → cap a 45 ──────────────────
        if adx < 20:
            combined = min(combined, 45)

        score = round(min(max(combined, 0), 100), 1)

        # Classificazione per spiegazione
        if adx < 20:
            reason = f"laterale (ADX {adx:.0f})"
        elif di_plus > di_minus and adx >= 25:
            reason = f"trend rialzista (ADX {adx:.0f})"
        elif di_minus > di_plus and adx >= 25:
            reason = f"trend ribassista (ADX {adx:.0f})"
        else:
            reason = f"trend debole (ADX {adx:.0f})"

        return {
            "score":  score,
            "detail": f"ADX={adx:.1f}, DI+={di_plus:.1f}, DI-={di_minus:.1f}, MA: {ma_count_above}/3",
            "reason": reason,
        }

    # ─────────────────────────────────────────────────────
    # MACD  (peso 25%)
    # ─────────────────────────────────────────────────────
    def _score_macd(self) -> dict:
        hist  = float(self.row.get("MACD_hist",   0))
        cross = float(self.row.get("MACD_cross",  0))
        macd  = float(self.row.get("MACD",        0))

        # Base: histogram
        ref = max(abs(macd), 0.001)
        if hist > 0:
            score = 55 + min(hist / ref * 25, 35)
        else:
            score = 45 + max(hist / ref * 25, -45)

        # Crossover recente
        if   cross ==  1: score += 20   # bullish cross = forte segnale
        elif cross == -1: score -= 20

        # Accelerazione: histogram cresce rispetto a ieri?
        if len(self.df) >= 2:
            prev_hist = float(self.df.iloc[-2].get("MACD_hist", hist))
            if hist > 0 and hist > prev_hist:
                score += 8    # momentum in accelerazione
            elif hist < 0 and hist < prev_hist:
                score -= 8

        score = round(min(max(score, 0), 100), 1)
        return {
            "score":  score,
            "detail": f"hist={hist:.3f}, cross={int(cross)}",
            "reason": ("bullish cross" if cross == 1 else
                       "bearish cross" if cross == -1 else
                       "momentum+" if hist > 0 else "momentum-"),
        }

    # ─────────────────────────────────────────────────────
    # VOLUME  (peso 20%)
    # Fix: 5 fasce invece di 3
    # ─────────────────────────────────────────────────────
    def _score_volume(self) -> dict:
        ratio = float(self.row.get("Volume_ratio", 1.0))
        vsig  = int(self.row.get("Volume_signal",  0))

        # 5 fasce ricalibrate: volume neutro (0.8-1.5x) ora vale 58-82
        # In precedenza la mediana era 48 → ora è 58, ceiling invariato
        if   ratio >= 2.0:  base = 100  # surge istituzionale
        elif ratio >= 1.5:  base = 82   # forte
        elif ratio >= 1.0:  base = 58   # normale → su neutro ora
        elif ratio >= 0.7:  base = 38   # debole
        elif ratio >= 0.5:  base = 18   # molto debole
        else:               base = 5    # quasi zero

        # Direzione del volume — neutro meno penalizzante
        if   vsig ==  1: score = base
        elif vsig == -1: score = max(5, 100 - base)
        else:            score = base * 0.75   # 0.65→0.75: giornate normali meno penalizzate

        score = round(min(max(score, 0), 100), 1)

        if   ratio >= 2.0: label = "surge forte"
        elif ratio >= 1.5: label = "volume alto"
        elif ratio >= 0.8: label = "volume normale"
        elif ratio >= 0.5: label = "volume debole"
        else:              label = "volume critico"

        return {
            "score":  score,
            "detail": f"ratio={ratio:.2f}x",
            "reason": label + (" ↑" if vsig == 1 else " ↓" if vsig == -1 else ""),
        }

    # ─────────────────────────────────────────────────────
    # ATR / RISK-REWARD  (peso 15%)
    # ─────────────────────────────────────────────────────
    def _score_atr_rr(self) -> dict:
        """
        Fix: usa ATR×2 come stop e ATR×3 come target (non BB_lower/upper).
        BB_lower può essere vicinissimo al prezzo → RR esplode a 22:1 (falso).
        ATR è la misura corretta della volatilità reale.
        """
        atr      = float(self.row.get("ATR",      0))
        close    = float(self.row.get("Close",    1))
        bb_upper = float(self.row.get("BB_upper", close))

        if close <= 0 or atr <= 0:
            return {"score": 50, "detail": "N/A", "reason": "dati mancanti"}

        # Stop: ATR×2 sotto il close (come usa il backtester)
        sl     = close - atr * config.ATR_STOP_MULTIPLIER
        # Target: minimo tra ATR×3 e BB_upper (non superare la banda)
        tgt_atr = close + atr * config.ATR_TARGET_MULTIPLIER
        target  = min(tgt_atr, bb_upper) if bb_upper > close else tgt_atr

        risk   = close - sl       # sempre ATR×2, mai zero
        reward = target - close

        # Cap: RR massimo credibile per swing = 4:1
        rr = min(reward / risk, 4.0) if risk > 0 else 1.0

        # Curve ricalibrate: RR 1.5:1 = 75, RR 2.0:1 = 90
        # La mediana reale è ~1.4:1 → ora atterrano su 65-70 invece di 40
        if   rr >= 2.0: rr_score = 90 + min((rr - 2.0) * 10, 10)
        elif rr >= 1.5: rr_score = 70 + (rr - 1.5) / 0.5 * 20
        elif rr >= 1.0: rr_score = 45 + (rr - 1.0) / 0.5 * 25
        elif rr >= 0.6: rr_score = 15 + (rr - 0.6) / 0.4 * 30
        else:           rr_score = max(0, rr / 0.6 * 15)

        # Percentile ATR: zona ideale = né troppo bassa né troppo alta
        if "ATR" in self.df.columns and len(self.df) >= 30:
            atr_hist   = self.df["ATR"].dropna()
            percentile = (atr_hist <= atr).sum() / len(atr_hist) * 100
            if   25 <= percentile <= 75: perc_score = 100
            elif percentile < 25:        perc_score = (percentile / 25) * 70
            elif percentile <= 85:       perc_score = 100 - ((percentile - 75) / 10) * 40
            else:                        perc_score = max(0, 60 - (percentile - 85) * 4)
        else:
            percentile = 50
            perc_score = 50

        score   = round(rr_score * 0.6 + perc_score * 0.4, 1)
        atr_pct = atr / close * 100
        return {
            "score":  score,
            "detail": f"RR={rr:.2f}:1, ATR={atr_pct:.1f}%",
            "reason": f"RR={rr:.2f}:1 | ATR {percentile:.0f}°pct",
        }

    # ─────────────────────────────────────────────────────
    # MEAN REVERSION  (peso 10%)
    # RSI + Bollinger combinati — entrambi misurano la stessa cosa
    # Peso ridotto da 35% a 10% per evitare doppio conteggio
    # ─────────────────────────────────────────────────────
    def _score_mean_reversion(self) -> dict:
        rsi     = float(self.row.get("RSI",         50))
        bb_pos  = float(self.row.get("BB_position", 0.5))

        # RSI score
        if   rsi <= config.RSI_OVERSOLD:   rsi_s = 100
        elif rsi >= config.RSI_OVERBOUGHT: rsi_s = 0
        elif rsi <= 50:
            rsi_s = 40 + (50 - rsi) / (50 - config.RSI_OVERSOLD) * 30
        else:
            rsi_s = 40 - (rsi - 50) / (config.RSI_OVERBOUGHT - 50) * 30

        # BB score (inverso: vicino lower = alto)
        bb_s = (1 - bb_pos) * 100

        # Media semplice: entrambi misurano mean reversion
        score = round((rsi_s + bb_s) / 2, 1)

        if   rsi < config.RSI_OVERSOLD:    label = f"RSI oversold ({rsi:.0f})"
        elif rsi > config.RSI_OVERBOUGHT:  label = f"RSI overbought ({rsi:.0f})"
        elif bb_pos < 0.3:                 label = f"vicino BB lower"
        elif bb_pos > 0.7:                 label = f"vicino BB upper"
        else:                              label = f"zona neutrale"

        return {
            "score":  score,
            "detail": f"RSI={rsi:.1f}, BB={bb_pos:.0%}",
            "reason": label,
        }

    # ─────────────────────────────────────────────────────
    # FILTRI HARD
    # Bloccano il segnale indipendentemente dallo score
    # ─────────────────────────────────────────────────────
    def _check_hard_filters(self) -> tuple:
        row     = self.row
        adx     = float(row.get("ADX",          0))
        di_minus= float(row.get("DI_minus",     0))
        di_plus = float(row.get("DI_plus",      0))
        vol_r   = float(row.get("Volume_ratio", 1))
        bb_pos  = float(row.get("BB_position",  0.5))
        macd_h  = float(row.get("MACD_hist",    0))

        # Filtro 1: Volume davvero critico (< 0.4x, non 0.5x)
        # 0.5x bloccava troppi giorni normali di basso volume
        if vol_r < 0.4:
            return True, f"Volume critico ({vol_r:.2f}x < 0.40x)"

        # Filtro 2: Trend ribassista forte (ADX alto + DI- domina)
        if adx > config.HARD_FILTER_ADX_BEAR_MAX and di_minus > di_plus:
            return True, f"Downtrend forte (ADX {adx:.0f} + DI- {di_minus:.0f} > DI+ {di_plus:.0f})"

        # Filtro 3: Prezzo in cima al canale BB con momentum negativo
        if bb_pos > config.HARD_FILTER_BB_TOP_ZONE and macd_h < 0:
            return True, f"Prezzo vicino BB upper ({bb_pos:.0%}) + MACD negativo"

        # NOTA: RR basso non viene bloccato qui — il componente ATR_RR
        # già penalizza score basso quando RR < 1.0.

        # Filtro 5: ATR percentile troppo basso → mercato compresso, segnali rumore
        try:
            atr_hist = self.df["ATR"].dropna()   # fix: era df (undefined), ora self.df
            if len(atr_hist) >= 20:
                atr_val  = float(atr_hist.iloc[-1])
                pct_rank = (atr_hist <= atr_val).sum() / len(atr_hist) * 100
                if pct_rank < 30:
                    return True, f"ATR percentile basso ({pct_rank:.0f}° < 30°) — mercato compresso"
        except Exception:
            pass

        return False, ""

    # ─────────────────────────────────────────────────────
    # REGIME DI MERCATO
    # Applica moltiplicatore in base a VIX e Fear&Greed
    # (VIX e F&G vengono iniettati dal main.py se disponibili)
    # ─────────────────────────────────────────────────────
    def _market_regime_multiplier(self) -> tuple:
        vix = float(getattr(self, "vix_value", 20))
        fg  = float(getattr(self, "fg_value",  50))

        # Moltiplicatori più miti: il mercato in fear è spesso opportunità
        # VIX 27 + F&G 18 = condizione attuale → moltiplicatore massimo ×0.90, non ×0.82
        if vix > config.REGIME_VIX_PANIC:          # >40
            return 0.80, f"⚠️ VIX panico ({vix:.0f}): score ×0.80"
        elif vix > config.REGIME_VIX_HIGH:          # >25
            if fg < config.REGIME_FG_EXTREME_FEAR:  # <20
                return 0.90, f"VIX alto ({vix:.0f}) + Extreme Fear ({fg:.0f}): ×0.90"
            return 0.95, f"VIX elevato ({vix:.0f}): ×0.95"
        elif fg < config.REGIME_FG_EXTREME_FEAR:
            return 0.92, f"Extreme Fear ({fg:.0f}): ×0.92"
        return 1.0, ""

    # ─────────────────────────────────────────────────────
    # TIPO DI SETUP
    # Distingue trend following da mean reversion
    # ─────────────────────────────────────────────────────
    def _classify_setup(self, breakdown: dict) -> str:
        trend_s = breakdown["trend"]["score"]
        mr_s    = breakdown["mr"]["score"]
        macd_s  = breakdown["macd"]["score"]
        adx     = float(self.row.get("ADX", 0))
        rsi     = float(self.row.get("RSI", 50))

        # Trend following: ADX alto + trend score alto
        if adx >= 25 and trend_s >= 60:
            return "TREND_FOLLOWING"
        # Mean reversion: RSI/BB oversold + trend score basso
        if rsi < 38 and mr_s >= 65 and trend_s < 50:
            return "MEAN_REVERSION"
        # MACD momentum puro
        if macd_s >= 70 and trend_s >= 45:
            return "MOMENTUM"
        return "MIXED"

    # ─────────────────────────────────────────────────────
    # SPIEGAZIONE
    # ─────────────────────────────────────────────────────
    def _build_explanation(self, breakdown, score, signal,
                           block_reason, regime_note, setup_type,
                           rs_adj=0, earn_pen=False) -> str:
        lines = []

        if block_reason:
            lines.append(f"🚫 BLOCCATO: {block_reason}")
        if regime_note:
            lines.append(f"📊 Regime: {regime_note}")
        if rs_adj != 0:
            lines.append(f"📈 RS vs SP500: {rs_adj:+d}pts")
        if earn_pen:
            lines.append(f"⚠️ Earnings imminenti: score ×0.85")

        strong = [(k, v) for k, v in breakdown.items() if v["score"] > 65]
        weak   = [(k, v) for k, v in breakdown.items() if v["score"] < 35]

        if strong:
            s = ", ".join(f"{k.upper()} ({v['reason']})" for k, v in strong)
            lines.append(f"✅ {s}")
        if weak:
            w = ", ".join(f"{k.upper()} ({v['reason']})" for k, v in weak)
            lines.append(f"⚠️  {w}")

        lines.append(f"Setup: {setup_type} | Score: {score}/100 → {signal}")
        return " | ".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# FUNZIONE RAPIDA
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# HELPER — progressione score
# ─────────────────────────────────────────────────────────────────────────────

def _build_score_steps(raw, regime_mult, rs_adj, earn_pen, mtf_adj, final,
                       earn_label="", earn_delta=0) -> list:
    """
    Costruisce la catena di trasformazioni dello score — visibile nella UI.
    Es: 68.0 → ×0.90 regime → -4 RS → -7 MTF → -15% earnings → 47.2 finale
    """
    steps = []
    val = round(raw, 1)
    steps.append({"label": "Base (indicatori)", "value": val, "delta": None})

    if regime_mult != 1.0:
        new_val = round(val * regime_mult, 1)
        steps.append({"label": f"×{regime_mult:.2f} regime mercato",
                      "value": new_val, "delta": round(new_val - val, 1)})
        val = new_val

    if rs_adj != 0:
        new_val = round(min(max(val + rs_adj, 0), 100), 1)
        steps.append({"label": "RS vs SP500",
                      "value": new_val, "delta": rs_adj})
        val = new_val

    if mtf_adj != 0:
        new_val = round(min(max(val + mtf_adj, 0), 100), 1)
        steps.append({"label": "Multi-timeframe",
                      "value": new_val, "delta": mtf_adj})
        val = new_val

    if earn_pen and earn_delta != 0:
        new_val = round(min(max(val + earn_delta, 0), 100), 1)
        label   = f"Earnings — {earn_label}" if earn_label else "Penalità earnings"
        steps.append({"label": label, "value": new_val, "delta": earn_delta})
        val = new_val

    # Step finale se cap penalità o arrotondamenti hanno modificato il valore
    if round(val, 1) != round(final, 1):
        steps.append({"label": "Cap penalità / aggiustamenti",
                      "value": round(final, 1),
                      "delta": round(final - val, 1)})

    return steps


def score_ticker(df: pd.DataFrame, ticker: str = "",
                 vix: float = 20, fg: float = 50,
                 rs_data: dict = None, earnings_data: dict = None) -> dict:
    """Shortcut con supporto regime, RS vs SP500 ed earnings."""
    s = Scorer(df, ticker)
    s.vix_value     = vix
    s.fg_value      = fg
    s.rs_data       = rs_data      or {}
    s.earnings_data = earnings_data or {}
    return s.compute()


# ─────────────────────────────────────────────────────────────────────────────
# TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from data_fetcher import DataFetcher
    from indicators   import compute_indicators

    fetcher  = DataFetcher()
    tickers  = ["AAPL", "NVDA", "MSFT", "TSLA", "AMD", "INTC", "JPM"]
    results  = []

    print("\n" + "="*65)
    print("TEST Scorer v3 — pesi rivisti + fix bug + filtri hard")
    print("="*65)

    for ticker in tickers:
        df_raw = fetcher.get_historical(ticker)
        if df_raw is None: continue
        df     = compute_indicators(df_raw)
        result = score_ticker(df, ticker, vix=26.6, fg=18)
        results.append(result)

        sig_icon = {"BUY":"🟢","WATCH":"🟡","SKIP":"🔴"}.get(result["signal"],"⚪")
        block    = f" 🚫 {result['block_reason'][:40]}" if result["hard_block"] else ""
        print(f"\n{'─'*60}")
        print(f"  {sig_icon} {ticker:<6}  Score: {result['score']:>5}/100  "
              f"({result['setup_type']}){block}")
        print(f"{'─'*60}")
        for key, val in result["breakdown"].items():
            bar = "█" * int(val["score"]/5) + "░" * (20 - int(val["score"]/5))
            w   = config.WEIGHTS[key]
            print(f"  {key:<8} [{bar}] {val['score']:>5}  ({w}%)  {val['reason']}")
        if result["regime_note"]:
            print(f"\n  📊 {result['regime_note']}")

    print(f"\n\n{'='*65}")
    print("CLASSIFICA FINALE")
    print("="*65)
    results.sort(key=lambda x: x["score"], reverse=True)
    for i, r in enumerate(results, 1):
        sig_icon = {"BUY":"🟢","WATCH":"🟡","SKIP":"🔴"}.get(r["signal"],"⚪")
        print(f"  {i}. {sig_icon} {r['ticker']:<6} {r['score']:>5}/100  "
              f"{r['signal']:<6}  {r['setup_type']}")
    print("\n✅ Scorer v3 completato!")
