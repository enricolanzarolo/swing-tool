# config.py — Configurazione centrale del tool v2

import os
from dotenv import load_dotenv
load_dotenv()

# ─────────────────────────────────────────────────────────────────
# CAPITALE E RISK MANAGEMENT
# ─────────────────────────────────────────────────────────────────
CAPITAL             = 2000
MAX_RISK_PER_TRADE  = 0.02
TRADE_COMMISSION    = 1.0
EUR_USD_DEFAULT     = 1.08

# ─────────────────────────────────────────────────────────────────
# WATCHLIST
# ─────────────────────────────────────────────────────────────────
# Watchlist v2 — ottimizzata su backtest 2 anni (Marzo 2026)
# Rimossi i ticker con Profit Factor < 0.70 che distruggevano capitale:
#   AAPL (PF 0.69), MSFT (PF 0.41), QCOM (PF 0.32)
#   PFE  (PF 0.47), MRNA (PF 0.60), XOM  (PF 0.59)
# Mantenuti i ticker con PF > 1.0 + aggiunti sostituti ad alta volatilità strutturale
# Watchlist v4 — Marzo 2026, dopo position sizing adattivo
# Rimossi AMD (PF 0.85), META (PF 0.81), JPM (PF 0.82)
# 7 ticker finali: tutti con PF ≥ 1.30 su 2 anni di dati puliti e bias-free
#
# PF finale per ticker:
#   GOOGL 3.95 | GS 2.55 | BAC 1.91 | JNJ 1.73 | INTC 1.56 | CVX 1.30 | TSLA 1.10*
#   (* TSLA borderline ma tenuto per diversificazione EV/consumer)
# Watchlist v5 — Marzo 2026, dopo backtest candidati
# Rimossi: MU(1.04), CVX(1.03), TSLA(1.10), JNJ(0.94), MS(0.59), COP(0.22), ABT(0.49)
# MDT(1.29) in osservazione — borderline, pochi trade
#
# PF per ticker:
#   GOOGL 3.95 | GS 2.55 | BAC 1.91 | INTC 1.85 | C 1.77 | EOG 1.46
#   WFC 1.44 | TXN 1.36 | MDT 1.29*
WATCHLIST = {
    "Tech":          ["GOOGL"],
    "Finance":       ["BAC", "GS", "WFC", "C"],
    "Energy":        ["EOG"],
    "Semiconductor": ["INTC", "TXN"],
    "Healthcare":    ["MDT"],               # in osservazione PF 1.29
}
# Totale: 9 ticker validati + MDT in osservazione
# Revisione trimestrale: giugno 2026
ALL_TICKERS = [t for tickers in WATCHLIST.values() for t in tickers]

# ─────────────────────────────────────────────────────────────────
# PARAMETRI SWING
# ─────────────────────────────────────────────────────────────────
SWING_PERIOD_DAYS = 365 * 2
SIGNAL_INTERVAL   = "1d"
HOLDING_DAYS_MIN  = 3
HOLDING_DAYS_MAX  = 20

# ─────────────────────────────────────────────────────────────────
# INDICATORI
# ─────────────────────────────────────────────────────────────────
RSI_OVERSOLD    = 35
RSI_OVERBOUGHT  = 65
RSI_PERIOD      = 14

MACD_FAST   = 12
MACD_SLOW   = 26
MACD_SIGNAL = 9

BB_PERIOD = 20
BB_STD    = 2.0

ATR_PERIOD            = 14
ATR_STOP_MULTIPLIER   = 2.0
ATR_TARGET_MULTIPLIER = 3.0

VOLUME_AVG_PERIOD    = 20
VOLUME_SURGE_FACTOR  = 1.5

ADX_PERIOD   = 14
ADX_TRENDING = 25

# ─────────────────────────────────────────────────────────────────
# PESI v2 — rivisti per massimizzare win rate swing
#
# TREND     30%  — variabile più predittiva per swing
# MACD      25%  — momentum direzionale
# VOLUME    20%  — conferma istituzionale del movimento
# ATR_RR    15%  — qualità del setup risk/reward
# MR        10%  — mean reversion (RSI+BB combinati, erano 35% → ora 10%)
#
# Somma = 100
# ─────────────────────────────────────────────────────────────────
WEIGHTS = {
    "trend":  30,
    "macd":   25,
    "volume": 20,
    "atr_rr": 15,
    "mr":     10,   # mean reversion: RSI + BB combinati
}
assert sum(WEIGHTS.values()) == 100

# ─────────────────────────────────────────────────────────────────
# SOGLIE SEGNALE
# ─────────────────────────────────────────────────────────────────
# Soglie v3 — calibrate su distribuzioni reali dei componenti:
# Volume neutro = 58, ATR_RR mediana = 65 → score base tipico 45-60
# BUY=57 → ~15-18% giorni in condizioni neutre = 1 trade ogni 5-7gg per ticker
# Prima era BUY=52 con mediana componenti troppo bassa → falsi segnali
SIGNAL_BUY_THRESHOLD  = 57
SIGNAL_HOLD_THRESHOLD = 40

# ─────────────────────────────────────────────────────────────────
# POSITION SIZING ADATTIVO
# ─────────────────────────────────────────────────────────────────
# Quando il setup è "già esaurito" (RSI o BB in zona overbought)
# il sistema entra lo stesso ma con size ridotta.
# Questo cattura i trade validi ma limita il danno sui falsi segnali
# da indicator crowding (il fenomeno dei trade score-alto che perdono).
OVEREXTENDED_RSI_THRESHOLD  = 68    # RSI > 68 → setup potenzialmente esaurito
OVEREXTENDED_BB_THRESHOLD   = 0.82  # BB position > 82% → prezzo già in zona alta
OVEREXTENDED_SIZE_FACTOR    = 0.5   # rischia il 50% del normale in questi casi
OVEREXTENDED_SCORE_PENALTY  = 0.88  # ×0.88 allo score (appare come step esplicito)

# Cap massimo penalità cumulative (regime + MTF + RS + earnings)
# Senza cap: 72 base → 43 finale → mai BUY. Con cap: minimo 57 → BUY possibile
MAX_PENALTY_CAP = 20   # max 20 punti di penalità totale

# ─────────────────────────────────────────────────────────────────
# FILTRI HARD — bloccano il segnale indipendentemente dallo score
# ─────────────────────────────────────────────────────────────────
HARD_FILTER_VOLUME_MIN     = 0.4    # volume < 0.4x media → segnale sospeso (0.5 era troppo aggressivo)
HARD_FILTER_ADX_BEAR_MAX   = 35     # ADX > 35 + ribassista → NO BUY
HARD_FILTER_BB_TOP_ZONE    = 0.80   # prezzo > 80% del canale BB → NO BUY

# ─────────────────────────────────────────────────────────────────
# REGIME DI MERCATO
# ─────────────────────────────────────────────────────────────────
REGIME_VIX_HIGH          = 25
REGIME_VIX_PANIC         = 40      # alzato: panico solo sopra 40, non 35
REGIME_FG_EXTREME_FEAR   = 20
REGIME_BUY_THRESHOLD_HIGH = 65

# ─────────────────────────────────────────────────────────────────
# NEWS
# ─────────────────────────────────────────────────────────────────
NEWS_MAX_AGE_HOURS = 48
NEWS_WEIGHT        = 10

# ─────────────────────────────────────────────────────────────────
# API KEYS
# ─────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GROQ_API_KEY      = os.getenv("GROQ_API_KEY", "")
NEWSAPI_KEY       = os.getenv("NEWSAPI_KEY", "")

# ─────────────────────────────────────────────────────────────────
# FLASK
# ─────────────────────────────────────────────────────────────────
FLASK_HOST  = "127.0.0.1"
FLASK_PORT  = 5000
FLASK_DEBUG = True
