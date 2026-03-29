# modules/news_sentiment.py — Modulo 5: News & Sentiment
# Recupera notizie RSS, Fear & Greed Index, VIX
# Produce un sentiment score -100/+100 per ogni ticker

import feedparser
import requests
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

# ─────────────────────────────────────────────────────────────────────────────
# PAROLE CHIAVE PER SENTIMENT
# ─────────────────────────────────────────────────────────────────────────────

BULLISH_WORDS = [
    "beat", "beats", "exceeds", "surges", "jumps", "rises", "gains",
    "upgrade", "upgraded", "buy", "outperform", "strong", "bullish",
    "record", "growth", "profit", "revenue", "partnership", "deal",
    "breakthrough", "launch", "innovation", "expands", "dividend",
    "buyback", "acquisition", "positive", "optimistic", "rally",
]

BEARISH_WORDS = [
    "miss", "misses", "falls", "drops", "declines", "slides", "plunges",
    "downgrade", "downgraded", "sell", "underperform", "weak", "bearish",
    "loss", "lawsuit", "probe", "investigation", "fine", "penalty",
    "recall", "layoffs", "cuts", "warning", "concern", "risk",
    "negative", "disappoints", "crash", "fraud", "scandal",
]

# ─────────────────────────────────────────────────────────────────────────────
# CLASSE PRINCIPALE
# ─────────────────────────────────────────────────────────────────────────────

class NewsSentiment:
    """
    Recupera e analizza news e sentiment di mercato.
    Produce un punteggio sentiment -100 (bearish) → +100 (bullish).
    """

    def __init__(self):
        self._fear_greed_cache = None
        self._vix_cache        = None

    # ─────────────────────────────────────────
    # NEWS RSS PER TICKER
    # ─────────────────────────────────────────

    def get_ticker_news(self, ticker: str, max_age_hours: int = config.NEWS_MAX_AGE_HOURS) -> list:
        """
        Scarica news da 3 fonti diverse e le deduplicca per titolo.
        1. yfinance .news  (fonte principale, più ricca)
        2. Yahoo Finance RSS feed 1 (headline)
        3. Yahoo Finance RSS feed 2 (search)
        Ritorna lista di dict: {title, published, sentiment_score, url, source}
        """
        seen    = set()   # deduplicazione per titolo
        articles = []
        cutoff  = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

        # ── FONTE 1: yfinance .news (la più ricca) ────────────────────────
        try:
            import yfinance as yf
            yf_news = yf.Ticker(ticker).news or []
            for item in yf_news[:30]:
                title = item.get("title", "")
                if not title or title in seen:
                    continue

                # Timestamp
                ts  = item.get("providerPublishTime", 0)
                pub = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None
                if pub and pub < cutoff:
                    continue

                seen.add(title)
                score = self._score_headline(title)
                articles.append({
                    "title":           title,
                    "published":       pub.strftime("%Y-%m-%d %H:%M") if pub else "N/A",
                    "sentiment_score": score,
                    "url":             item.get("link", ""),
                    "source":          item.get("publisher", "Yahoo Finance"),
                })
        except Exception as e:
            print(f"[NewsSentiment] yfinance news {ticker}: {e}")

        # ── FONTE 2: Yahoo Finance RSS headline ───────────────────────────
        rss_feeds = [
            f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US",
            f"https://finance.yahoo.com/rss/headline?s={ticker}",
        ]
        for url in rss_feeds:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:20]:
                    title = entry.get("title", "")
                    if not title or title in seen:
                        continue

                    pub = None
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        try:
                            pub = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                        except Exception:
                            pub = None

                    if pub and pub < cutoff:
                        continue

                    seen.add(title)
                    score = self._score_headline(title)
                    articles.append({
                        "title":           title,
                        "published":       pub.strftime("%Y-%m-%d %H:%M") if pub else "N/A",
                        "sentiment_score": score,
                        "url":             entry.get("link", ""),
                        "source":          "Yahoo Finance RSS",
                    })
            except Exception as e:
                print(f"[NewsSentiment] RSS {ticker}: {e}")

        # Ordina per data (più recenti prima)
        def sort_key(a):
            try:
                return datetime.strptime(a["published"], "%Y-%m-%d %H:%M")
            except Exception:
                return datetime.min
        articles.sort(key=sort_key, reverse=True)

        return articles[:25]  # max 25 articoli totali

    def _score_headline(self, title: str) -> int:
        """
        Analizza il titolo di un articolo e ritorna score:
        +1 per ogni parola bullish, -1 per ogni parola bearish.
        """
        title_lower = title.lower()
        score = 0
        for w in BULLISH_WORDS:
            if w in title_lower:
                score += 1
        for w in BEARISH_WORDS:
            if w in title_lower:
                score -= 1
        return max(-3, min(3, score))  # capped -3 / +3

    # ─────────────────────────────────────────
    # FEAR & GREED INDEX
    # da alternative.me (API pubblica, gratuita)
    # ─────────────────────────────────────────

    def get_fear_greed(self) -> dict:
        """
        Ritorna il Fear & Greed Index attuale (0=extreme fear, 100=extreme greed).
        Nota: questo indice è per crypto ma è usato anche come proxy del sentiment
        generale sul rischio — lo usiamo come fattore secondario.
        """
        if self._fear_greed_cache:
            return self._fear_greed_cache

        try:
            r    = requests.get("https://api.alternative.me/fng/?limit=1", timeout=5)
            data = r.json()["data"][0]
            val  = int(data["value"])
            cat  = data["value_classification"]

            result = {
                "value":          val,
                "classification": cat,
                "signal":         self._fg_to_signal(val),
                "score":          self._fg_to_score(val),
            }
            self._fear_greed_cache = result
            return result

        except Exception as e:
            print(f"[NewsSentiment] Fear&Greed non disponibile: {e}")
            return {"value": 50, "classification": "Neutral", "signal": "neutro", "score": 0}

    def _fg_to_signal(self, val: int) -> str:
        if val <= 25:  return "extreme fear (contrarian BUY)"
        if val <= 40:  return "fear (possibile rimbalzo)"
        if val <= 60:  return "neutro"
        if val <= 75:  return "greed (attenzione)"
        return               "extreme greed (possibile top)"

    def _fg_to_score(self, val: int) -> int:
        """
        Contrarian: fear estrema = opportunità di acquisto (+score)
        Greed estrema = mercato surriscaldato (-score)
        """
        if val <= 25:  return +15   # extreme fear = opportunità
        if val <= 40:  return +8    # fear = lieve opportunità
        if val <= 60:  return 0     # neutro
        if val <= 75:  return -5    # greed = cautela
        return                -12   # extreme greed = pericolo

    # ─────────────────────────────────────────
    # VIX — Volatility Index
    # da Yahoo Finance
    # ─────────────────────────────────────────

    def get_vix(self) -> dict:
        """
        Recupera il VIX attuale (indice di paura del mercato azionario).
        VIX < 15 = mercato tranquillo
        VIX 15-25 = volatilità normale
        VIX > 30 = paura, possibili opportunità contrarian
        VIX > 40 = panico, massima cautela
        """
        if self._vix_cache:
            return self._vix_cache

        try:
            import yfinance as yf
            vix_data = yf.Ticker("^VIX").fast_info
            vix_val  = getattr(vix_data, "last_price", None)

            if not vix_val:
                df = yf.download("^VIX", period="2d", progress=False, multi_level_index=False)
                if not df.empty:
                    df.columns = [c.capitalize() for c in df.columns]
                    vix_val = float(df["Close"].iloc[-1])

            if vix_val:
                vix_val = float(vix_val)
                result  = {
                    "value":  round(vix_val, 2),
                    "signal": self._vix_signal(vix_val),
                    "score":  self._vix_score(vix_val),
                }
                self._vix_cache = result
                return result

        except Exception as e:
            print(f"[NewsSentiment] VIX non disponibile: {e}")

        return {"value": 20.0, "signal": "normale", "score": 0}

    def _vix_signal(self, vix: float) -> str:
        if vix < 15:   return "mercato tranquillo (bassa volatilità)"
        if vix < 20:   return "volatilità bassa-normale"
        if vix < 25:   return "volatilità nella norma"
        if vix < 30:   return "volatilità elevata — cautela"
        if vix < 40:   return "paura di mercato — attenzione"
        return               "panico — rischio molto alto"

    def _vix_score(self, vix: float) -> int:
        """
        VIX alto = rischio → penalizza il segnale
        VIX molto alto = panico = possibile contrarian opportunity
        """
        if vix < 15:   return +5    # tranquillo, buono per swing
        if vix < 20:   return +3
        if vix < 25:   return 0
        if vix < 30:   return -5
        if vix < 40:   return -10
        return               -15    # panico: penalizza forte

    # ─────────────────────────────────────────
    # SENTIMENT AGGREGATO PER TICKER
    # ─────────────────────────────────────────

    def get_full_sentiment(self, ticker: str) -> dict:
        """
        Aggrega: news RSS + Fear&Greed + VIX
        Ritorna sentiment score finale e breakdown.
        """
        # News
        news      = self.get_ticker_news(ticker)
        fg        = self.get_fear_greed()
        vix       = self.get_vix()

        # Score news: media dei punteggi normalizzata -100/+100
        if news:
            raw_news_score = sum(a["sentiment_score"] for a in news) / len(news)
            # Scala da [-3,+3] a [-100,+100]
            news_score = int(raw_news_score / 3 * 100)
        else:
            news_score = 0

        # Score combinato (pesato)
        # News 50%, Fear&Greed 25%, VIX 25%
        combined = int(
            news_score     * 0.50 +
            fg["score"]    * 0.25 * (100/15) +   # normalizza da [-15,+15]
            vix["score"]   * 0.25 * (100/15)
        )
        combined = max(-100, min(100, combined))

        # Classificazione
        if combined >= 30:   sentiment_label = "🟢 Bullish"
        elif combined >= 10: sentiment_label = "🟡 Leggermente Bullish"
        elif combined >= -10:sentiment_label = "⚪ Neutro"
        elif combined >= -30:sentiment_label = "🟠 Leggermente Bearish"
        else:                sentiment_label = "🔴 Bearish"

        # Bonus/malus sul score tecnico (usato nel Modulo 6+)
        score_adjustment = int(combined / 100 * config.NEWS_WEIGHT)

        return {
            "ticker":           ticker,
            "sentiment_score":  combined,
            "sentiment_label":  sentiment_label,
            "score_adjustment": score_adjustment,

            "news": {
                "count":   len(news),
                "score":   news_score,
                "articles": news[:5],  # prime 5 notizie
            },
            "fear_greed": fg,
            "vix":        vix,
        }


# ─────────────────────────────────────────────────────────────────────────────
# FUNZIONE RAPIDA
# ─────────────────────────────────────────────────────────────────────────────

def get_sentiment(ticker: str) -> dict:
    return NewsSentiment().get_full_sentiment(ticker)


# ─────────────────────────────────────────────────────────────────────────────
# STAMPA FORMATTATA
# ─────────────────────────────────────────────────────────────────────────────

def print_sentiment(s: dict):
    print(f"\n{'─'*55}")
    print(f"  📰 SENTIMENT — {s['ticker']}  →  {s['sentiment_label']}  ({s['sentiment_score']:+d}/100)")
    print(f"{'─'*55}")

    vix = s["vix"]
    fg  = s["fear_greed"]
    n   = s["news"]

    print(f"  VIX          : {vix['value']:.1f}  —  {vix['signal']}")
    print(f"  Fear & Greed : {fg['value']}/100  —  {fg['signal']}")
    print(f"  News ({n['count']} articoli): score {n['score']:+d}/100")

    if n["articles"]:
        print(f"\n  Ultime notizie:")
        for a in n["articles"]:
            icon  = "🟢" if a["sentiment_score"] > 0 else ("🔴" if a["sentiment_score"] < 0 else "⚪")
            title = a["title"][:70] + "…" if len(a["title"]) > 70 else a["title"]
            print(f"    {icon} [{a['published']}] {title}")

    adj = s["score_adjustment"]
    print(f"\n  Impatto sul score tecnico: {adj:+d} punti")


# ─────────────────────────────────────────────────────────────────────────────
# TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    analyzer  = NewsSentiment()
    tickers   = ["AAPL", "NVDA", "TSLA", "JPM"]

    print("\n" + "="*55)
    print("TEST Modulo 5 — News & Sentiment")
    print("="*55)

    # Dati globali (una volta sola)
    print("\n📊 DATI DI MERCATO GLOBALI")
    print("─"*55)
    vix = analyzer.get_vix()
    fg  = analyzer.get_fear_greed()
    print(f"  VIX          : {vix['value']:.1f}  →  {vix['signal']}")
    print(f"  Fear & Greed : {fg['value']}/100  →  {fg['classification']}  ({fg['signal']})")

    # Sentiment per ticker
    print("\n📰 SENTIMENT PER TICKER")
    results = []
    for ticker in tickers:
        print(f"\n  Analizzando {ticker}...", end=" ", flush=True)
        s = analyzer.get_full_sentiment(ticker)
        results.append(s)
        print(f"✓  {s['sentiment_label']}  ({s['sentiment_score']:+d})")
        time.sleep(0.5)  # evita rate limiting

    # Stampa dettagliata
    for s in results:
        print_sentiment(s)

    # Riepilogo
    print(f"\n\n{'='*55}")
    print("📋 RIEPILOGO SENTIMENT")
    print("="*55)
    for s in sorted(results, key=lambda x: x["sentiment_score"], reverse=True):
        adj = s["score_adjustment"]
        print(f"  {s['sentiment_label']:<28} {s['ticker']:<6}  adj: {adj:+d} punti")

    print(f"\n✅ Modulo 5 completato!")
