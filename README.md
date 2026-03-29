# 📈 SwingTool — Trading Analyzer by Enrico

Tool di analisi swing trading con AI, indicatori tecnici e backtesting.
Questo progetto è ancora in fase di testing, realizzato principalmente con AI

---

##  Setup

```bash
# 1. Installa le dipendenze
pip install -r requirements.txt

# 2. Crea il file con le API key
cp .env.example .env
# Apri .env e inserisci la tua ANTHROPIC_API_KEY

# 3. Testa il Modulo 1 (data fetcher)
python modules/data_fetcher.py
```

---

## Struttura del progetto

```
swing_tool/
├── config.py               ← ⚙️  Tutti i parametri (modifica qui)
├── requirements.txt        ← 📦 Dipendenze Python
├── .env.example            ← 🔑 Template chiavi API
├── main.py                 ← 🌐 App Flask (Modulo 8)
│
├── modules/
│   ├── data_fetcher.py     ← ✅ MOD 1: Dati Yahoo Finance
│   ├── indicators.py       ← ⏳ MOD 2: RSI, MACD, BB, ATR...
│   ├── scorer.py           ← ⏳ MOD 3: Sistema pesi e score
│   ├── signals.py          ← ⏳ MOD 4: Segnali BUY/SELL
│   ├── news_sentiment.py   ← ⏳ MOD 5: News e sentiment
│   ├── ai_analyst.py       ← ⏳ MOD 6: Analisi Claude AI
│   └── backtester.py       ← ⏳ MOD 7: Backtesting
│
├── static/
│   ├── style.css           ← ⏳ MOD 8: Stile UI
│   └── app.js              ← ⏳ MOD 8: Logica frontend
│
└── templates/
    └── index.html          ← ⏳ MOD 8: Interfaccia web
```

---

##  Moduli (stato avanzamento)

| # | Modulo            | Stato  | Descrizione                          |
|---|-------------------|--------|--------------------------------------|
| 1 | DataFetcher       | ✅ Done | Yahoo Finance, prezzi, EUR/USD       |
| 2 | Indicators        | ⏳     | RSI, MACD, BB, ATR, ADX, Volume      |
| 3 | Scorer            | ⏳     | Sistema pesi → score 0-100           |
| 4 | Signals           | ⏳     | BUY/SELL/WATCH + entry/exit/SL       |
| 5 | News & Sentiment  | ⏳     | Feed RSS, VIX, Fear&Greed            |
| 6 | AI Analyst        | ⏳     | Analisi Claude su ogni segnale       |
| 7 | Backtester        | ⏳     | Win rate, rendimento 2 anni          |
| 8 | UI Web            | ⏳     | Dashboard Flask interattiva          |
| 9 | Multi-Scanner     | ⏳     | Scan intera watchlist in parallelo   |
|10 | Ottimizzazioni    | ⏳     | Fine-tuning pesi, alerting           |

---

## Parametri principali (config.py)

| Parametro            | Default  | Descrizione                        |
|----------------------|----------|------------------------------------|
| `CAPITAL`            | 2000 EUR | Capitale totale trading  (esempio) |
| `MAX_RISK_PER_TRADE` | 2%       | Rischio massimo per operazione     |
| `SIGNAL_BUY_THRESHOLD` | 55    | Score minimo per segnale BUY       |
| `RSI_OVERSOLD`       | 35       | Soglia RSI ipervenduto             |
| `ATR_STOP_MULTIPLIER`| 2.0x     | Moltiplicatore stop loss su ATR    |

---

## ⚠️ Disclaimer

Questo tool è a scopo educativo e informativo e di testing.
Il trading comporta rischi reali. Non investire più di quanto sei disposto a perdere.
Nessun algoritmo garantisce profitti.
