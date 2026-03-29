# modules/ai_analyst.py — Modulo 6: Analisi AI con Groq
# Usa Groq (llama3-70b, gratuito) per produrre un'analisi in italiano

import requests
import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURAZIONE GROQ
# ─────────────────────────────────────────────────────────────────────────────

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL   = "llama-3.3-70b-versatile"   # modello aggiornato (il precedente è dismesso)


def _groq_headers() -> dict:
    key = os.getenv("GROQ_API_KEY", "")
    if not key:
        raise ValueError("GROQ_API_KEY non trovata nel file .env")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type":  "application/json",
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLASSE PRINCIPALE
# ─────────────────────────────────────────────────────────────────────────────

class AIAnalyst:
    """
    Prende il segnale tecnico + sentiment e chiede a Groq
    un'analisi ragionata in italiano con verdetto finale.
    """

    def analyze(self, signal: dict, sentiment: dict) -> dict:
        """
        Analizza un ticker combinando segnale tecnico e sentiment.
        Ritorna dict con: verdict, reasoning, risk_notes, confidence
        """
        prompt = self._build_prompt(signal, sentiment)

        try:
            response = requests.post(
                GROQ_API_URL,
                headers=_groq_headers(),
                json={
                    "model":       GROQ_MODEL,
                    "messages":    [
                        {
                            "role":    "system",
                            "content": (
                                "Sei un analista finanziario esperto di swing trading. "
                                "Rispondi SEMPRE e SOLO in italiano. "
                                "Sei diretto, pratico e onesto sui rischi. "
                                "Non dare mai garanzie di profitto. "
                                "Rispondi in formato JSON come richiesto."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.3,    # bassa per risposte più precise
                    "max_tokens":  600,
                },
                timeout=20,
            )

            if response.status_code != 200:
                raise ValueError(f"Groq error {response.status_code}: {response.text[:200]}")

            content = response.json()["choices"][0]["message"]["content"]
            return self._parse_response(content, signal)

        except Exception as e:
            print(f"[AIAnalyst] Errore: {e}")
            return self._fallback_analysis(signal, sentiment)

    # ─────────────────────────────────────────
    # COSTRUZIONE PROMPT
    # ─────────────────────────────────────────

    def _build_prompt(self, signal: dict, sentiment: dict) -> str:
        ticker  = signal["ticker"]
        score   = signal["score"]
        sig     = signal["signal"]
        bd      = signal.get("breakdown", {})

        # Indicatori tecnici
        indicators = "\n".join([
            f"  - {k.upper()}: score {v['score']}/100 ({v['reason']})"
            for k, v in bd.items()
        ])

        # Prezzi operativi
        if sig == "BUY":
            prices = (
                f"  Entry: ${signal.get('entry_usd','N/A')} (€{signal.get('entry_eur','N/A')})\n"
                f"  Stop Loss: ${signal.get('stop_loss_usd','N/A')} (-{signal.get('pct_to_sl','N/A')}%)\n"
                f"  Target: ${signal.get('target_usd','N/A')} (+{signal.get('pct_to_target','N/A')}%)\n"
                f"  Risk/Reward: {signal.get('risk_reward','N/A')}:1\n"
                f"  Azioni: {signal.get('shares','N/A')} × €{signal.get('entry_eur','N/A')} = €{signal.get('invested_eur','N/A')}"
            )
        else:
            prices = f"  Nessuna operazione proposta (segnale: {sig})"

        # Sentiment
        fg  = sentiment.get("fear_greed", {})
        vix = sentiment.get("vix", {})
        news_articles = sentiment.get("news", {}).get("articles", [])
        news_titles = "\n".join([
            f"  [{a['sentiment_score']:+d}] {a['title'][:80]}"
            for a in news_articles[:5]
        ])

        # Multi-timeframe
        mtf_summary = signal.get("mtf_summary", "")
        rs_info     = signal.get("rs_info", "")
        earn_info   = signal.get("earn_info", "")
        setup_type  = signal.get("setup_type", "MIXED")
        score_steps = signal.get("score_steps_text", "")

        return f"""Analizza questo segnale di swing trading e rispondi in JSON.

TICKER: {ticker}
SEGNALE TECNICO: {sig} (score FINALE: {score}/100)
TIPO DI SETUP: {setup_type}

PROGRESSIONE SCORE:
{score_steps if score_steps else "  N/A"}

INDICATORI TECNICI:
{indicators}

ALLINEAMENTO MULTI-TIMEFRAME: {mtf_summary if mtf_summary else "N/A"}
FORZA RELATIVA VS SP500: {rs_info if rs_info else "N/A"}
EARNINGS: {earn_info if earn_info else "Nessun earnings imminente"}

PREZZI OPERATIVI:
{prices}

SENTIMENT DI MERCATO:
  Fear & Greed Index: {fg.get('value','N/A')}/100 ({fg.get('classification','N/A')})
  VIX: {vix.get('value','N/A')} ({vix.get('signal','N/A')})
  Sentiment news: {sentiment.get('sentiment_label','N/A')} ({sentiment.get('sentiment_score',0):+d}/100)

ULTIME NOTIZIE:
{news_titles if news_titles else "  Nessuna notizia recente"}

Sei un analista di swing trading. Considera TUTTI i dati sopra.
Il setup {setup_type} ha implicazioni diverse: TREND_FOLLOWING richiede conferma direzionale,
MEAN_REVERSION richiede oversold genuino, MOMENTUM richiede volume e accelerazione.

Rispondi SOLO con questo JSON (nessun testo fuori dal JSON):
{{
  "verdict": "COMPRA ORA" | "ASPETTA" | "NON ENTRARE",
  "confidence": "alta" | "media" | "bassa",
  "reasoning": "2-3 frasi che spiegano perché, citando i dati specifici (score, MTF, RS, earnings)",
  "risk_notes": "1-2 frasi sui rischi specifici incluso regime mercato e earnings",
  "best_case": "scenario ottimistico in 1 frase con target price",
  "worst_case": "scenario pessimistico in 1 frase con livello di stop"
}}"""

    # ─────────────────────────────────────────
    # PARSING RISPOSTA
    # ─────────────────────────────────────────

    def _parse_response(self, content: str, signal: dict) -> dict:
        """Estrae il JSON dalla risposta di Groq."""
        try:
            # Cerca il JSON nella risposta
            start = content.find("{")
            end   = content.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(content[start:end])
                # Verifica campi obbligatori
                for field in ["verdict", "confidence", "reasoning"]:
                    if field not in data:
                        data[field] = "N/A"
                data["raw"] = content
                return data
        except Exception as e:
            print(f"[AIAnalyst] Parsing error: {e}")

        return self._fallback_analysis(signal, {})

    # ─────────────────────────────────────────
    # FALLBACK (se Groq non risponde)
    # ─────────────────────────────────────────

    def _fallback_analysis(self, signal: dict, sentiment: dict) -> dict:
        sig   = signal.get("signal", "WATCH")
        score = signal.get("score",  0)

        if sig == "BUY" and score >= 60:
            verdict    = "COMPRA ORA"
            confidence = "media"
            reasoning  = f"Gli indicatori tecnici mostrano un segnale positivo con score {score}/100. Il sistema di pesi indica condizioni favorevoli all'acquisto."
        elif sig == "BUY":
            verdict    = "ASPETTA"
            confidence = "bassa"
            reasoning  = f"Segnale BUY debole (score {score}/100). Attendere conferma da volume e trend prima di entrare."
        elif sig == "WATCH":
            verdict    = "ASPETTA"
            confidence = "media"
            reasoning  = f"Mercato in fase di attesa (score {score}/100). Monitorare i prossimi 2-3 giorni per un segnale più chiaro."
        else:
            verdict    = "NON ENTRARE"
            confidence = "alta"
            reasoning  = f"Condizioni tecniche sfavorevoli (score {score}/100). Meglio aspettare un setup migliore."

        return {
            "verdict":    verdict,
            "confidence": confidence,
            "reasoning":  reasoning,
            "risk_notes": "Analisi AI non disponibile — basati sul segnale tecnico.",
            "best_case":  "N/A",
            "worst_case": "N/A",
            "raw":        "fallback",
        }


# ─────────────────────────────────────────────────────────────────────────────
# FUNZIONE RAPIDA
# ─────────────────────────────────────────────────────────────────────────────

def analyze(signal: dict, sentiment: dict) -> dict:
    return AIAnalyst().analyze(signal, sentiment)


# ─────────────────────────────────────────────────────────────────────────────
# STAMPA FORMATTATA
# ─────────────────────────────────────────────────────────────────────────────

def print_analysis(ticker: str, result: dict):
    verdict_icons = {
        "COMPRA ORA":  "🟢",
        "ASPETTA":     "🟡",
        "NON ENTRARE": "🔴",
    }
    icon = verdict_icons.get(result.get("verdict", ""), "⚪")
    conf = result.get("confidence", "N/A")

    print(f"\n{'─'*58}")
    print(f"  🤖 ANALISI AI — {ticker}")
    print(f"{'─'*58}")
    print(f"  Verdetto     : {icon} {result.get('verdict','N/A')}  (confidenza: {conf})")
    print(f"\n  📝 Ragionamento:")
    print(f"  {result.get('reasoning','N/A')}")
    print(f"\n  ⚠️  Rischi:")
    print(f"  {result.get('risk_notes','N/A')}")
    if result.get("best_case") and result["best_case"] != "N/A":
        print(f"\n  📈 Scenario ottimistico: {result['best_case']}")
        print(f"  📉 Scenario pessimistico: {result['worst_case']}")


# ─────────────────────────────────────────────────────────────────────────────
# TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from data_fetcher    import DataFetcher
    from indicators      import compute_indicators
    from scorer          import score_ticker
    from signals         import generate_signal
    from news_sentiment  import NewsSentiment

    # Carica .env
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

    fetcher   = DataFetcher()
    sentiment = NewsSentiment()
    analyst   = AIAnalyst()

    tickers = ["TSLA", "JPM", "MSFT"]

    print("\n" + "="*58)
    print("TEST Modulo 6 — Analisi AI con Groq")
    print("="*58)

    # Verifica API key
    key = os.getenv("GROQ_API_KEY", "")
    if not key:
        print("\n❌ GROQ_API_KEY non trovata!")
        print("   Apri il file .env e aggiungi:")
        print("   GROQ_API_KEY=gsk_tuachiavegroq")
        exit()
    else:
        print(f"\n✅ GROQ_API_KEY trovata ({key[:8]}...)")

    config.EUR_USD_DEFAULT = fetcher.eur_usd

    for ticker in tickers:
        print(f"\n{'='*58}")
        print(f"  Analizzando {ticker}...")
        print(f"{'='*58}")

        df_raw  = fetcher.get_historical(ticker)
        if df_raw is None:
            continue

        df      = compute_indicators(df_raw)
        scored  = score_ticker(df, ticker)
        sig     = generate_signal(df, scored)
        sent    = sentiment.get_full_sentiment(ticker)
        ai      = analyst.analyze(sig, sent)

        # Stampa segnale tecnico
        print(f"  Score tecnico : {scored['score']}/100  →  {scored['signal']}")
        print(f"  Sentiment     : {sent['sentiment_label']} ({sent['sentiment_score']:+d})")

        # Stampa analisi AI
        print_analysis(ticker, ai)

    print(f"\n\n✅ Modulo 6 completato!")
