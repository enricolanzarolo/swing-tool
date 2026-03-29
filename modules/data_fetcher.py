# modules/data_fetcher.py — v2 (fixed yfinance compat)
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

def _safe(obj, attr, default=None):
    try:
        val = getattr(obj, attr, default)
        return val if val is not None else default
    except Exception:
        return default

class DataFetcher:
    def __init__(self):
        self.eur_usd = self._fetch_eur_usd()
        print(f"[DataFetcher] Tasso EUR/USD attuale: {self.eur_usd:.4f}")

    def _fetch_eur_usd(self) -> float:
        try:
            fi   = yf.Ticker("EURUSD=X").fast_info
            rate = _safe(fi, "last_price")
            if rate and float(rate) > 0:
                return float(rate)
        except Exception as e:
            print(f"[DataFetcher] Warning EUR/USD fallback: {e}")
        return config.EUR_USD_DEFAULT

    def usd_to_eur(self, price_usd: float) -> float:
        return price_usd / self.eur_usd

    def get_historical(self, ticker: str, days: int = config.SWING_PERIOD_DAYS,
                       interval: str = config.SIGNAL_INTERVAL) -> Optional[pd.DataFrame]:
        end   = datetime.today()
        start = end - timedelta(days=days)
        try:
            df = yf.download(
                ticker,
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                interval=interval,
                auto_adjust=True,
                progress=False,
                multi_level_index=False,
            )
            if df is None or df.empty:
                print(f"[DataFetcher] Nessun dato per {ticker}")
                return None
            # Appiattisce multi-index residui
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = ["_".join(c).strip("_") for c in df.columns]
            # Normalizza nomi (prima lettera maiuscola)
            df.columns = [c.capitalize() for c in df.columns]
            # Controlla colonne necessarie
            required = {"Close", "Volume"}
            missing  = required - set(df.columns)
            if missing:
                print(f"[DataFetcher] Colonne mancanti per {ticker}: {missing}")
                return None
            df.dropna(subset=["Close", "Volume"], inplace=True)
            df.index = pd.to_datetime(df.index)
            print(f"[DataFetcher] {ticker}: {len(df)} candele ({interval})")
            return df
        except Exception as e:
            print(f"[DataFetcher] Errore fetch {ticker}: {e}")
            return None

    def get_current_price(self, ticker: str) -> Optional[dict]:
        try:
            fi         = yf.Ticker(ticker).fast_info
            price_usd  = _safe(fi, "last_price")
            prev_close = _safe(fi, "previous_close")
            # Fallback: ultima riga storica
            if not price_usd:
                df = self.get_historical(ticker, days=5)
                if df is not None and not df.empty:
                    price_usd  = float(df["Close"].iloc[-1])
                    prev_close = float(df["Close"].iloc[-2]) if len(df) > 1 else price_usd
                else:
                    return None
            price_usd  = float(price_usd)
            prev_close = float(prev_close) if prev_close else price_usd
            price_eur  = self.usd_to_eur(price_usd)
            change_pct = (price_usd - prev_close) / prev_close * 100 if prev_close else 0.0
            return {
                "ticker":     ticker,
                "price_usd":  round(price_usd, 4),
                "price_eur":  round(price_eur, 4),
                "change_pct": round(change_pct, 2),
                "volume":     int(_safe(fi, "three_month_average_volume", 0) or 0),
                "market_cap": int(_safe(fi, "market_cap", 0) or 0),
                "eur_usd":    self.eur_usd,
                "timestamp":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        except Exception as e:
            print(f"[DataFetcher] Errore prezzo {ticker}: {e}")
            return None

    def get_company_info(self, ticker: str) -> dict:
        try:
            info = yf.Ticker(ticker).info
            return {
                "name":           info.get("longName", ticker),
                "sector":         info.get("sector", "N/A"),
                "industry":       info.get("industry", "N/A"),
                "country":        info.get("country", "N/A"),
                "pe_ratio":       info.get("trailingPE", None),
                "eps":            info.get("trailingEps", None),
                "revenue_growth": info.get("revenueGrowth", None),
                "debt_to_equity": info.get("debtToEquity", None),
                "free_cashflow":  info.get("freeCashflow", None),
                "beta":           info.get("beta", None),
                "52w_high":       info.get("fiftyTwoWeekHigh", None),
                "52w_low":        info.get("fiftyTwoWeekLow", None),
                "avg_volume":     info.get("averageVolume", None),
                "description":    info.get("longBusinessSummary", "")[:300],
            }
        except Exception as e:
            print(f"[DataFetcher] Errore info {ticker}: {e}")
            return {"name": ticker, "sector": "N/A"}

    def fetch_all_watchlist(self) -> dict:
        results = {}
        total   = len(config.ALL_TICKERS)
        for i, ticker in enumerate(config.ALL_TICKERS, 1):
            print(f"[DataFetcher] Scaricando {ticker} ({i}/{total})...")
            df = self.get_historical(ticker)
            if df is not None and len(df) > 50:
                results[ticker] = df
            else:
                print(f"[DataFetcher] {ticker} saltato: dati insufficienti")
        print(f"\n[DataFetcher] Pronti {len(results)}/{total} ticker")
        return results

    # ─────────────────────────────────────────
    # MULTI-TIMEFRAME
    # ─────────────────────────────────────────

    def get_multitimeframe(self, ticker: str) -> dict:
        """
        Scarica dati su 3 timeframe: weekly, daily, 4H.
        Ritorna indicatori chiave per ciascuno.
        """
        import yfinance as yf
        result = {}

        specs = [
            ("weekly", "1wk", "1y"),
            ("daily",  "1d",  "6mo"),
            ("h4",     "1h",  "60d"),
        ]

        for name, interval, period in specs:
            try:
                df = yf.download(ticker, period=period, interval=interval,
                                 progress=False, multi_level_index=False)
                if df is None or len(df) < 10:
                    result[name] = {"error": "dati insufficienti"}
                    continue

                df.columns = [c.capitalize() for c in df.columns]

                # EMA 20 e 50
                df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
                df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()

                # RSI 14
                delta = df["Close"].diff()
                gain  = delta.clip(lower=0).ewm(span=14, adjust=False).mean()
                loss  = (-delta.clip(upper=0)).ewm(span=14, adjust=False).mean()
                rs    = gain / loss.replace(0, 1e-9)
                df["RSI"] = 100 - 100 / (1 + rs)

                # MACD
                ema12 = df["Close"].ewm(span=12, adjust=False).mean()
                ema26 = df["Close"].ewm(span=26, adjust=False).mean()
                df["MACD_hist"] = ema12 - ema26 - (ema12 - ema26).ewm(span=9, adjust=False).mean()

                last  = df.iloc[-1]
                close = float(last["Close"])
                ema20 = float(last["EMA20"])
                ema50 = float(last["EMA50"])
                rsi   = float(last["RSI"])
                macd_h= float(last["MACD_hist"])

                # Trend del timeframe
                above20 = close > ema20
                above50 = close > ema50
                if above20 and above50 and rsi > 50:
                    trend = "bullish"
                elif not above20 and not above50 and rsi < 50:
                    trend = "bearish"
                elif above20 and not above50:
                    trend = "misto_rialzista"
                else:
                    trend = "misto_ribassista"

                result[name] = {
                    "close":    round(close, 2),
                    "ema20":    round(ema20, 2),
                    "ema50":    round(ema50, 2),
                    "rsi":      round(rsi, 1),
                    "macd_h":   round(macd_h, 4),
                    "above_ema20": above20,
                    "above_ema50": above50,
                    "trend":    trend,
                }
            except Exception as e:
                result[name] = {"error": str(e)}

        # Allineamento: quanti timeframe sono bullish?
        bullish_count = sum(
            1 for tf in result.values()
            if isinstance(tf, dict) and "bull" in tf.get("trend", "")
        )
        total_tf = sum(1 for tf in result.values() if "error" not in tf)

        if   total_tf == 0:    alignment = "unknown"
        elif bullish_count == total_tf: alignment = "full_bullish"
        elif bullish_count == 0:        alignment = "full_bearish"
        elif bullish_count >= total_tf * 0.6: alignment = "mostly_bullish"
        else:                           alignment = "mostly_bearish"

        result["alignment"]     = alignment
        result["bullish_count"] = bullish_count
        result["total_tf"]      = total_tf

        return result

    # ─────────────────────────────────────────
    # RELATIVE STRENGTH vs SP500
    # ─────────────────────────────────────────

    def get_relative_strength(self, ticker: str, days: int = 20) -> dict:
        """
        Calcola la performance relativa del ticker vs SP500 negli ultimi N giorni.
        RS > 0 = sovraperforma il mercato → bonus score
        RS < 0 = sottoperforma → penalità score
        """
        import yfinance as yf
        try:
            period = f"{days + 10}d"
            t_df   = yf.download(ticker,  period=period, progress=False, multi_level_index=False)
            sp_df  = yf.download("^GSPC", period=period, progress=False, multi_level_index=False)

            if t_df is None or sp_df is None or len(t_df) < 5 or len(sp_df) < 5:
                return {"error": "dati insufficienti", "rs": 0, "label": "N/A"}

            t_df.columns  = [c.capitalize() for c in t_df.columns]
            sp_df.columns = [c.capitalize() for c in sp_df.columns]

            t_ret  = float((t_df["Close"].iloc[-1]  - t_df["Close"].iloc[-min(days, len(t_df)-1)])
                           / t_df["Close"].iloc[-min(days, len(t_df)-1)]  * 100)
            sp_ret = float((sp_df["Close"].iloc[-1] - sp_df["Close"].iloc[-min(days, len(sp_df)-1)])
                           / sp_df["Close"].iloc[-min(days, len(sp_df)-1)] * 100)

            rs = round(t_ret - sp_ret, 2)

            if   rs >= 5:    label = "forte sovraperformance"
            elif rs >= 2:    label = "sovraperformance"
            elif rs >= -2:   label = "in linea col mercato"
            elif rs >= -5:   label = "sottoperformance"
            else:            label = "forte sottoperformance"

            return {
                "ticker_ret": round(t_ret, 2),
                "sp500_ret":  round(sp_ret, 2),
                "rs":         rs,
                "label":      label,
                "days":       days,
            }
        except Exception as e:
            return {"error": str(e), "rs": 0, "label": "N/A"}

    # ─────────────────────────────────────────
    # EARNINGS DATE
    # ─────────────────────────────────────────

    def get_earnings_date(self, ticker: str) -> dict:
        """
        Recupera la data del prossimo earnings report.
        Se entro 5 giorni lavorativi → warning attivo.
        """
        import yfinance as yf
        from datetime import datetime, timedelta
        try:
            t    = yf.Ticker(ticker)
            cal  = t.calendar

            # yfinance restituisce dict con "Earnings Date"
            if cal is None:
                return {"date": None, "days_away": None, "warning": False}

            # Gestisci sia dict che DataFrame
            if hasattr(cal, "loc"):  # DataFrame
                try:
                    raw = cal.loc["Earnings Date"]
                    if hasattr(raw, "iloc"):
                        raw = raw.iloc[0]
                    earnings_dt = pd.Timestamp(raw).to_pydatetime()
                except Exception:
                    return {"date": None, "days_away": None, "warning": False}
            elif isinstance(cal, dict):
                raw = cal.get("Earnings Date", [None])
                if isinstance(raw, list):
                    raw = raw[0] if raw else None
                if raw is None:
                    return {"date": None, "days_away": None, "warning": False}
                earnings_dt = pd.Timestamp(raw).to_pydatetime()
            else:
                return {"date": None, "days_away": None, "warning": False}

            now       = datetime.now()
            delta     = (earnings_dt - now).days

            # Giorni lavorativi approssimati (esclude weekend)
            bdays = 0
            d     = now
            while d < earnings_dt and bdays < 30:
                d += timedelta(days=1)
                if d.weekday() < 5:
                    bdays += 1

            warning = 0 <= bdays <= 5

            return {
                "date":      earnings_dt.strftime("%Y-%m-%d"),
                "days_away": delta,
                "bdays_away": bdays,
                "warning":   warning,
                "label":     f"Earnings tra {bdays} giorni lavorativi" if warning
                             else f"Earnings: {earnings_dt.strftime('%d/%m/%Y')}",
            }
        except Exception as e:
            return {"date": None, "days_away": None, "warning": False, "error": str(e)}


if __name__ == "__main__":
    fetcher = DataFetcher()

    print("\n" + "="*50)
    print("TEST 1: Prezzo corrente AAPL")
    print("="*50)
    price = fetcher.get_current_price("AAPL")
    if price:
        print(f"  Prezzo USD : ${price['price_usd']}")
        print(f"  Prezzo EUR : €{price['price_eur']}")
        print(f"  Variazione : {price['change_pct']}%")
        print(f"  Timestamp  : {price['timestamp']}")
    else:
        print("  Errore nel recupero del prezzo")

    print("\n" + "="*50)
    print("TEST 2: Dati storici AAPL (30 giorni)")
    print("="*50)
    df = fetcher.get_historical("AAPL", days=30)
    if df is not None:
        print(f"  Righe      : {len(df)}")
        print(f"  Colonne    : {list(df.columns)}")
        print(f"  Dal        : {df.index[0].date()}")
        print(f"  Al         : {df.index[-1].date()}")
        print(f"  Close range: ${df['Close'].min():.2f} - ${df['Close'].max():.2f}")
    else:
        print("  Errore nel recupero storico")

    print("\n" + "="*50)
    print("TEST 3: Info azienda NVDA")
    print("="*50)
    info = fetcher.get_company_info("NVDA")
    for k, v in info.items():
        if k != "description":
            print(f"  {k}: {v}")

    print("\n✅ Modulo 1 completato!")
