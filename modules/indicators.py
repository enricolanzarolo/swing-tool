# modules/indicators.py — Modulo 2: Indicatori Tecnici
# Calcola RSI, MACD, Bollinger Bands, ATR, ADX, Volume su DataFrame OHLCV

import pandas as pd
import numpy as np
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

# ─────────────────────────────────────────────────────────────────────────────
# FUNZIONI BASE (calcoli manuali — no dipendenze esterne fragili)
# ─────────────────────────────────────────────────────────────────────────────

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def _sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()

def _true_range(df: pd.DataFrame) -> pd.Series:
    high  = df["High"]
    low   = df["Low"]
    close = df["Close"].shift(1)
    tr1   = high - low
    tr2   = (high - close).abs()
    tr3   = (low  - close).abs()
    return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

# ─────────────────────────────────────────────────────────────────────────────
# CLASSE PRINCIPALE
# ─────────────────────────────────────────────────────────────────────────────

class Indicators:
    """
    Riceve un DataFrame OHLCV e aggiunge tutte le colonne degli indicatori.
    Uso: df = Indicators(df).compute()
    """

    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()

    def compute(self) -> pd.DataFrame:
        """Calcola tutti gli indicatori e li aggiunge al DataFrame."""
        df = self.df

        # Controlla dati minimi
        if len(df) < config.MACD_SLOW + config.MACD_SIGNAL + 5:
            print("[Indicators] Warning: dati insufficienti per calcolo completo")

        df = self._rsi(df)
        df = self._macd(df)
        df = self._bollinger(df)
        df = self._atr(df)
        df = self._adx(df)
        df = self._volume(df)
        df = self._moving_averages(df)

        # Rimuove righe iniziali con NaN (warm-up degli indicatori)
        min_valid = max(
            config.MACD_SLOW + config.MACD_SIGNAL,
            config.BB_PERIOD,
            config.ADX_PERIOD * 2,
        )
        df = df.iloc[min_valid:].copy()
        df.dropna(subset=["RSI", "MACD", "BB_upper", "ATR", "ADX"], inplace=True)

        self.df = df
        return df

    # ─────────────────────────────────────────
    # RSI — Relative Strength Index
    # Misura la forza del movimento (0-100)
    # < 35 = ipervenduto (opportunità acquisto)
    # > 65 = ipercomprato (opportunità vendita)
    # ─────────────────────────────────────────

    def _rsi(self, df: pd.DataFrame) -> pd.DataFrame:
        period = config.RSI_PERIOD
        delta  = df["Close"].diff()
        gain   = delta.clip(lower=0)
        loss   = (-delta).clip(lower=0)

        avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
        avg_loss = loss.ewm(com=period - 1, adjust=False).mean()

        rs         = avg_gain / avg_loss.replace(0, np.nan)
        df["RSI"]  = 100 - (100 / (1 + rs))
        df["RSI"]  = df["RSI"].fillna(50)

        # Segnale RSI: +1 oversold, -1 overbought, 0 neutro
        df["RSI_signal"] = 0
        df.loc[df["RSI"] < config.RSI_OVERSOLD,   "RSI_signal"] =  1
        df.loc[df["RSI"] > config.RSI_OVERBOUGHT, "RSI_signal"] = -1

        return df

    # ─────────────────────────────────────────
    # MACD — Moving Average Convergence Divergence
    # Misura momentum e direzione del trend
    # Cross MACD > Signal = segnale rialzista
    # ─────────────────────────────────────────

    def _macd(self, df: pd.DataFrame) -> pd.DataFrame:
        ema_fast = _ema(df["Close"], config.MACD_FAST)
        ema_slow = _ema(df["Close"], config.MACD_SLOW)

        df["MACD"]        = ema_fast - ema_slow
        df["MACD_signal"] = _ema(df["MACD"], config.MACD_SIGNAL)
        df["MACD_hist"]   = df["MACD"] - df["MACD_signal"]

        # Crossover: +1 bullish cross, -1 bearish cross, 0 nessun cross
        df["MACD_cross"] = 0
        macd_above = df["MACD"] > df["MACD_signal"]
        df.loc[ macd_above & ~macd_above.shift(1).fillna(False), "MACD_cross"] =  1
        df.loc[~macd_above &  macd_above.shift(1).fillna(True),  "MACD_cross"] = -1

        return df

    # ─────────────────────────────────────────
    # BOLLINGER BANDS
    # Canale di volatilità attorno alla media
    # Prezzo vicino a banda lower = potenziale rimbalzo
    # ─────────────────────────────────────────

    def _bollinger(self, df: pd.DataFrame) -> pd.DataFrame:
        period = config.BB_PERIOD
        std    = config.BB_STD

        ma            = _sma(df["Close"], period)
        sigma         = df["Close"].rolling(period).std()

        df["BB_mid"]   = ma
        df["BB_upper"] = ma + std * sigma
        df["BB_lower"] = ma - std * sigma
        df["BB_width"] = (df["BB_upper"] - df["BB_lower"]) / df["BB_mid"]

        # Posizione del prezzo nel canale (0 = lower, 1 = upper)
        band_range         = df["BB_upper"] - df["BB_lower"]
        df["BB_position"]  = (df["Close"] - df["BB_lower"]) / band_range.replace(0, np.nan)
        df["BB_position"]  = df["BB_position"].clip(0, 1).fillna(0.5)

        # Segnale: +1 vicino lower (buy zone), -1 vicino upper (sell zone)
        df["BB_signal"] = 0
        df.loc[df["BB_position"] < 0.2, "BB_signal"] =  1
        df.loc[df["BB_position"] > 0.8, "BB_signal"] = -1

        return df

    # ─────────────────────────────────────────
    # ATR — Average True Range
    # Misura la volatilità per calcolare stop loss e target
    # ─────────────────────────────────────────

    def _atr(self, df: pd.DataFrame) -> pd.DataFrame:
        tr         = _true_range(df)
        df["ATR"]  = tr.ewm(span=config.ATR_PERIOD, adjust=False).mean()

        # Stop loss e target basati su ATR
        df["SL_distance"]     = df["ATR"] * config.ATR_STOP_MULTIPLIER
        df["Target_distance"] = df["ATR"] * config.ATR_TARGET_MULTIPLIER

        return df

    # ─────────────────────────────────────────
    # ADX — Average Directional Index
    # Misura la forza del trend (NON la direzione)
    # > 25 = trend forte (utile per swing)
    # ─────────────────────────────────────────

    def _adx(self, df: pd.DataFrame) -> pd.DataFrame:
        period = config.ADX_PERIOD
        high   = df["High"]
        low    = df["Low"]
        close  = df["Close"]

        # Directional Movement
        up_move   = high.diff()
        down_move = (-low.diff())

        plus_dm  = up_move.where((up_move > down_move) & (up_move > 0),   0)
        minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0)

        tr        = _true_range(df)
        atr       = tr.ewm(span=period, adjust=False).mean()

        plus_di  = 100 * _ema(plus_dm,  period) / atr.replace(0, np.nan)
        minus_di = 100 * _ema(minus_dm, period) / atr.replace(0, np.nan)

        dx_denom = (plus_di + minus_di).replace(0, np.nan)
        dx        = 100 * (plus_di - minus_di).abs() / dx_denom

        df["ADX"]       = dx.ewm(span=period, adjust=False).mean().fillna(0)
        df["DI_plus"]   = plus_di.fillna(0)
        df["DI_minus"]  = minus_di.fillna(0)

        # Segnale tendenza direzionale
        df["ADX_trend"] = 0
        trending        = df["ADX"] > config.ADX_TRENDING
        df.loc[trending & (df["DI_plus"] > df["DI_minus"]), "ADX_trend"] =  1  # up
        df.loc[trending & (df["DI_plus"] < df["DI_minus"]), "ADX_trend"] = -1  # down

        return df

    # ─────────────────────────────────────────
    # VOLUME
    # Conferma la validità del movimento
    # Volume alto + prezzo su = segnale forte
    # ─────────────────────────────────────────

    def _volume(self, df: pd.DataFrame) -> pd.DataFrame:
        period = config.VOLUME_AVG_PERIOD

        df["Volume_MA"]    = _sma(df["Volume"], period)
        df["Volume_ratio"] = df["Volume"] / df["Volume_MA"].replace(0, np.nan)
        df["Volume_ratio"] = df["Volume_ratio"].fillna(1)

        # OBV — On Balance Volume (accumulo/distribuzione)
        price_dir  = np.sign(df["Close"].diff()).fillna(0)
        df["OBV"]  = (df["Volume"] * price_dir).cumsum()

        # Segnale volume: +1 surge rialzista, -1 surge ribassista, 0 normale
        df["Volume_signal"] = 0
        surge = df["Volume_ratio"] > config.VOLUME_SURGE_FACTOR
        price_up   = df["Close"] > df["Close"].shift(1)
        price_down = df["Close"] < df["Close"].shift(1)
        df.loc[surge & price_up,   "Volume_signal"] =  1
        df.loc[surge & price_down, "Volume_signal"] = -1

        return df

    # ─────────────────────────────────────────
    # MOVING AVERAGES
    # MA50 e MA200 per trend di lungo periodo
    # ─────────────────────────────────────────

    def _moving_averages(self, df: pd.DataFrame) -> pd.DataFrame:
        df["MA20"]  = _sma(df["Close"], 20)
        df["MA50"]  = _sma(df["Close"], 50)
        df["MA200"] = _sma(df["Close"], 200)

        # Golden cross / Death cross
        df["MA_signal"] = 0
        above_ma20 = df["Close"] > df["MA20"]
        above_ma50 = df["Close"] > df["MA50"]
        df.loc[above_ma20 & above_ma50, "MA_signal"] =  1
        df.loc[~above_ma20 & ~above_ma50, "MA_signal"] = -1

        return df


# ─────────────────────────────────────────────────────────────────────────────
# FUNZIONE RAPIDA
# ─────────────────────────────────────────────────────────────────────────────

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Shortcut: compute_indicators(df) → df con tutti gli indicatori."""
    return Indicators(df).compute()


# ─────────────────────────────────────────────────────────────────────────────
# TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from data_fetcher import DataFetcher

    fetcher = DataFetcher()

    print("\n" + "="*55)
    print("TEST Modulo 2 — Indicatori su AAPL (2 anni)")
    print("="*55)

    df_raw = fetcher.get_historical("AAPL")
    if df_raw is None:
        print("❌ Errore fetch dati")
        exit()

    df = compute_indicators(df_raw)

    last = df.iloc[-1]

    print(f"\n📅 Data ultimo giorno  : {df.index[-1].date()}")
    print(f"💵 Close               : ${last['Close']:.2f}")
    print(f"\n── RSI ─────────────────────────────")
    print(f"   RSI ({config.RSI_PERIOD})          : {last['RSI']:.1f}  ", end="")
    if   last["RSI_signal"] ==  1: print("→ 🟢 OVERSOLD (buy zone)")
    elif last["RSI_signal"] == -1: print("→ 🔴 OVERBOUGHT (sell zone)")
    else:                          print("→ ⚪ neutro")

    print(f"\n── MACD ────────────────────────────")
    print(f"   MACD                : {last['MACD']:.3f}")
    print(f"   Signal              : {last['MACD_signal']:.3f}")
    print(f"   Histogram           : {last['MACD_hist']:.3f}  ", end="")
    if   last["MACD_hist"] > 0: print("→ 🟢 momentum positivo")
    else:                        print("→ 🔴 momentum negativo")

    print(f"\n── BOLLINGER BANDS ─────────────────")
    print(f"   Upper               : ${last['BB_upper']:.2f}")
    print(f"   Mid                 : ${last['BB_mid']:.2f}")
    print(f"   Lower               : ${last['BB_lower']:.2f}")
    print(f"   Posizione nel canale: {last['BB_position']:.0%}  ", end="")
    if   last["BB_signal"] ==  1: print("→ 🟢 vicino lower (buy)")
    elif last["BB_signal"] == -1: print("→ 🔴 vicino upper (sell)")
    else:                          print("→ ⚪ zona centrale")

    print(f"\n── ATR (volatilità) ────────────────")
    print(f"   ATR ({config.ATR_PERIOD})           : ${last['ATR']:.2f}")
    print(f"   Stop Loss distanza  : ${last['SL_distance']:.2f}")
    print(f"   Target distanza     : ${last['Target_distance']:.2f}")

    print(f"\n── ADX (forza trend) ───────────────")
    print(f"   ADX                 : {last['ADX']:.1f}  ", end="")
    if last["ADX"] > config.ADX_TRENDING: print("→ 🟢 trend forte")
    else:                                  print("→ ⚪ mercato laterale")
    print(f"   DI+                 : {last['DI_plus']:.1f}")
    print(f"   DI-                 : {last['DI_minus']:.1f}")

    print(f"\n── VOLUME ──────────────────────────")
    print(f"   Volume ratio        : {last['Volume_ratio']:.2f}x media  ", end="")
    if   last["Volume_signal"] ==  1: print("→ 🟢 surge rialzista")
    elif last["Volume_signal"] == -1: print("→ 🔴 surge ribassista")
    else:                              print("→ ⚪ volume normale")

    print(f"\n── MOVING AVERAGES ─────────────────")
    print(f"   MA20                : ${last['MA20']:.2f}")
    print(f"   MA50                : ${last['MA50']:.2f}")
    print(f"   MA200               : ${last.get('MA200', float('nan')):.2f}")

    print(f"\n── RIEPILOGO SEGNALI ───────────────")
    signals = {
        "RSI":     last["RSI_signal"],
        "MACD":    1 if last["MACD_hist"] > 0 else -1,
        "BB":      last["BB_signal"],
        "Volume":  last["Volume_signal"],
        "ADX":     last["ADX_trend"],
        "MA":      last["MA_signal"],
    }
    for name, val in signals.items():
        icon = "🟢 BUY" if val == 1 else ("🔴 SELL" if val == -1 else "⚪ neutro")
        print(f"   {name:<10}: {icon}")

    total_columns = len(df.columns)
    print(f"\n✅ Modulo 2 completato! ({total_columns} colonne calcolate su {len(df)} candele)")
