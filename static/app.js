// static/app.js — SwingTool Frontend

const API = "";   // stesso host Flask

// ─────────────────────────────────────────────────────────────────
// STATE
// ─────────────────────────────────────────────────────────────────
let currentTicker = null;
let charts        = {};
let scanData      = [];

// ─────────────────────────────────────────────────────────────────
// INIT
// ─────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  loadMarketData();
  setupScanBtn();
  setupTabs();
  // Auto-popola sidebar con watchlist dal template
  renderSidebarStatic();
});

// ─────────────────────────────────────────────────────────────────
// MARKET DATA (topbar pills)
// ─────────────────────────────────────────────────────────────────
async function loadMarketData() {
  try {
    const d = await fetchJSON("/api/market");
    const vix = d.vix?.value ?? 0;
    const fg  = d.fear_greed?.value ?? 50;
    const eur = d.eur_usd ?? 1.08;

    setEl("pill-vix",  vix.toFixed(1));
    setEl("pill-fg",   fg);
    setEl("pill-eur",  eur.toFixed(4));

    const vixEl = document.getElementById("pill-vix");
    if (vixEl) {
      vixEl.className = "value " + (vix > 30 ? "warn" : vix > 20 ? "" : "up");
    }
    const fgEl = document.getElementById("pill-fg");
    if (fgEl) {
      fgEl.className = "value " + (fg < 30 ? "warn" : fg > 70 ? "down" : "");
    }
  } catch(e) {
    console.warn("Market data non disponibile:", e);
  }
}

// ─────────────────────────────────────────────────────────────────
// SIDEBAR STATIC
// ─────────────────────────────────────────────────────────────────
function renderSidebarStatic() {
  const list = document.getElementById("ticker-list");
  if (!list || typeof WATCHLIST === "undefined") return;

  list.innerHTML = "";
  for (const [group, tickers] of Object.entries(WATCHLIST)) {
    const gDiv = document.createElement("div");
    gDiv.className = "ticker-group";
    gDiv.innerHTML = `<div class="group-label">${group}</div>`;

    for (const t of tickers) {
      const row = document.createElement("div");
      row.className = "ticker-row";
      row.id = `tr-${t}`;
      row.innerHTML = `
        <span class="ticker-name">${t}</span>
        <span class="ticker-price" id="tp-${t}">—</span>
        <span class="ticker-score" id="ts-${t}">—</span>
      `;
      row.addEventListener("click", () => loadTicker(t));
      gDiv.appendChild(row);
    }
    list.appendChild(gDiv);
  }
}

// ─────────────────────────────────────────────────────────────────
// SCAN ALL
// ─────────────────────────────────────────────────────────────────
function setupScanBtn() {
  const btn = document.getElementById("scan-btn");
  if (!btn) return;
  btn.addEventListener("click", runScan);
}

async function runScan() {
  const btn = document.getElementById("scan-btn");
  btn.textContent = "Scanning…";
  btn.classList.add("loading");
  showLoading("Scansione watchlist in corso…");

  try {
    const scanResponse = await fetchJSON("/api/scan");
    scanData = scanResponse.results ?? scanResponse;  // compatibile con entrambi i formati
    const scanStats = scanResponse.stats ?? null;

    // Mostra stats nella topbar se disponibili
    if (scanStats) {
      const pill = document.createElement("div");
      pill.className = "market-pill";
      pill.innerHTML = `<span class="label">Ultimo scan</span>
        <span class="value ${scanStats.buy>0?'up':''}">${scanStats.buy} BUY / ${scanStats.watch} WATCH</span>`;
      const spacer = document.querySelector("#topbar .spacer");
      if (spacer) spacer.insertAdjacentElement("beforebegin", pill);
    }

    // Aggiorna sidebar con score e prezzi
    for (const r of scanData) {
      const scoreEl = document.getElementById(`ts-${r.ticker}`);
      const priceEl = document.getElementById(`tp-${r.ticker}`);
      const rowEl   = document.getElementById(`tr-${r.ticker}`);

      if (scoreEl) {
        const cls = r.signal === "BUY" ? "buy" : r.signal === "WATCH" ? "watch" : "skip";
        // Icona earnings nella sidebar
        const earnIcon = r.earnings_level === "block"  ? " 🚨"
                       : r.earnings_level === "high"   ? " ⚠️"
                       : r.earnings_level === "medium" ? " 📅"
                       : "";
        scoreEl.innerHTML  = `${r.score}${earnIcon}`;
        scoreEl.className    = `ticker-score ${cls}`;
        if (rowEl) rowEl.className = `ticker-row ${cls}`;
      }
      if (priceEl && r.price_eur) {
        const sign = r.change_pct >= 0 ? "+" : "";
        priceEl.innerHTML = `€${r.price_eur}<br><small style="color:${r.change_pct>=0?'var(--green)':'var(--red)'}">${sign}${r.change_pct}%</small>`;
      }
    }

    // Se era aperto un ticker, ricarica
    if (currentTicker) loadTicker(currentTicker);

  } catch(e) {
    alert("Errore scan: " + e.message);
  } finally {
    btn.textContent = "▶ Scan Watchlist";
    btn.classList.remove("loading");
    hideLoading();
  }
}

// ─────────────────────────────────────────────────────────────────
// LOAD TICKER
// ─────────────────────────────────────────────────────────────────
async function loadTicker(ticker) {
  currentTicker = ticker;

  // Marca attivo in sidebar
  document.querySelectorAll(".ticker-row").forEach(r => r.classList.remove("active"));
  const row = document.getElementById(`tr-${ticker}`);
  if (row) row.classList.add("active");

  showLoading(`Analisi ${ticker} in corso…`);
  document.getElementById("welcome").style.display    = "none";
  document.getElementById("ticker-view").style.display = "block";

  try {
    const d = await fetchJSON(`/api/analyze/${ticker}`);
    renderTickerView(d);
    // Aggiorna badge sidebar con score FINALE (include MTF, RS, earnings)
    const finalScore = d.score?.score ?? 0;
    const finalSig   = d.score?.signal ?? "WATCH";
    const scoreEl = document.getElementById(`ts-${ticker}`);
    const rowEl   = document.getElementById(`tr-${ticker}`);
    if (scoreEl) {
      const cls = finalSig === "BUY" ? "buy" : finalSig === "WATCH" ? "watch" : "skip";
      scoreEl.textContent = finalScore;
      scoreEl.className   = `ticker-score ${cls}`;
      if (rowEl) rowEl.className = `ticker-row active ${cls}`;
    }
  } catch(e) {
    document.getElementById("ticker-view").innerHTML =
      `<div class="card card-body" style="color:var(--red)">❌ Errore: ${e.message}</div>`;
  } finally {
    hideLoading();
  }
}

// ─────────────────────────────────────────────────────────────────
// RENDER TICKER VIEW
// ─────────────────────────────────────────────────────────────────
function renderTickerView(d) {
  const { ticker, price, info, score, signal, sentiment, indicators, chart_data } = d;
  const sig    = score.signal;
  const sigCls = sig === "BUY" ? "buy" : sig === "WATCH" ? "watch" : "skip";
  const sigIcon= sig === "BUY" ? "▲ BUY" : sig === "WATCH" ? "◉ WATCH" : "▼ SKIP";

  const chgCls = price?.change_pct >= 0 ? "up" : "down";
  const chgSign= price?.change_pct >= 0 ? "+" : "";

  document.getElementById("ticker-view").innerHTML = `

    <!-- Header -->
    <div id="ticker-header">
      <div class="ticker-title">
        <div class="name">${ticker}</div>
        <div class="company">${info?.name ?? ""} · ${info?.sector ?? ""}</div>
      </div>
      <div class="ticker-price-block">
        <div class="price">$${price?.price_usd ?? "—"}</div>
        <div class="change ${chgCls}">${chgSign}${price?.change_pct ?? 0}%</div>
        <div class="eur-note">≈ €${price?.price_eur ?? "—"}</div>
      </div>
      <div class="signal-badge ${sigCls}">${sigIcon} — ${score.score}/100</div>
    </div>

    <!-- Earnings Warning Banner -->
    ${renderEarningsBanner(d.earnings)}

    <!-- Tabs -->
    <div class="tabs">
      <button class="tab-btn active" data-tab="analysis">📊 Analisi</button>
      <button class="tab-btn"        data-tab="trade">💰 Trade</button>
      <button class="tab-btn"        data-tab="charts">📈 Grafici</button>
      <button class="tab-btn"        data-tab="news">📰 News</button>
      <button class="tab-btn"        data-tab="backtest">🔁 Backtest</button>
    </div>

    <!-- TAB: ANALYSIS -->
    <div class="tab-panel active" id="tab-analysis">
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px;">

        <!-- Score Breakdown -->
        <div class="card">
          <div class="card-header">Score Breakdown</div>
          <div class="card-body">${renderScoreBreakdown(score)}</div>
        </div>

        <!-- Indicators -->
        <div class="card">
          <div class="card-header">Indicatori Tecnici</div>
          <div class="card-body">${renderIndicators(indicators, price)}</div>
        </div>

      </div>

      <!-- Multi-Timeframe + Relative Strength -->
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-top:16px">
        <div class="card">
          <div class="card-header">🕐 Allineamento Multi-Timeframe</div>
          <div class="card-body">${renderMultiTimeframe(d.multitimeframe)}</div>
        </div>
        <div class="card">
          <div class="card-header">📊 Forza Relativa vs S&P 500 (20gg)</div>
          <div class="card-body">${renderRelativeStrength(d.relative_strength)}</div>
        </div>
      </div>

      <!-- Key Levels -->
      <div class="card" style="margin-top:16px">
        <div class="card-header">Livelli Chiave</div>
        <div class="card-body">${renderKeyLevels(signal?.key_levels, price?.price_usd)}</div>
      </div>

      <!-- AI Analyst -->
      <div class="card" style="margin-top:16px" id="ai-card">
        <div class="card-header" style="display:flex;justify-content:space-between;align-items:center">
          <span>🤖 Analisi AI — llama-3.3-70b</span>
          <button onclick="loadAI('${ticker}')" id="ai-btn"
            style="background:var(--accent);border:none;color:#000;padding:5px 14px;
                   border-radius:4px;cursor:pointer;font-size:0.75rem;font-weight:700;
                   font-family:var(--sans)">
            ▶ Avvia analisi
          </button>
        </div>
        <div class="card-body" id="ai-body">
          <p style="color:var(--text-dim);font-size:0.78rem">
            Clicca "Avvia analisi" per ottenere il verdetto AI ragionato basato su tutti i dati del ticker
            (score, MTF, RS vs SP500, earnings, sentiment e notizie recenti).
          </p>
        </div>
      </div>
    </div>

    <!-- TAB: TRADE -->
    <div class="tab-panel" id="tab-trade">
      ${renderTradePanel(signal, sig)}
    </div>

    <!-- TAB: CHARTS -->
    <div class="tab-panel" id="tab-charts">
      <div class="card">
        <div class="card-header">Prezzo + Bollinger Bands (90 giorni)</div>
        <div class="card-body"><div class="chart-wrap"><canvas id="chart-price"></canvas></div></div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px">
        <div class="card">
          <div class="card-header">RSI (14)</div>
          <div class="card-body"><div class="chart-wrap" style="height:140px"><canvas id="chart-rsi"></canvas></div></div>
        </div>
        <div class="card">
          <div class="card-header">MACD</div>
          <div class="card-body"><div class="chart-wrap" style="height:140px"><canvas id="chart-macd"></canvas></div></div>
        </div>
      </div>
    </div>

    <!-- TAB: NEWS -->
    <div class="tab-panel" id="tab-news">
      ${renderNewsPanel(sentiment)}
    </div>

    <!-- TAB: BACKTEST -->
    <div class="tab-panel" id="tab-backtest">
      <div style="text-align:center;padding:20px">
        <button onclick="loadBacktest('${ticker}')" style="
          background:var(--accent);color:#fff;border:none;border-radius:6px;
          padding:10px 24px;font-family:var(--sans);font-weight:700;cursor:pointer;font-size:0.9rem">
          ▶ Avvia Backtest ${ticker} (2 anni)
        </button>
      </div>
      <div id="backtest-result"></div>
    </div>
  `;

  setupTabs();

  // Carica grafici dopo render
  setTimeout(() => renderCharts(chart_data, price?.price_usd), 100);
}

// ─────────────────────────────────────────────────────────────────
// SCORE BREAKDOWN
// ─────────────────────────────────────────────────────────────────
function renderScoreBreakdown(score) {
  const weights = { trend:30, macd:25, volume:20, atr_rr:15, mr:10 };
  let html = "";

  // Barre indicatori
  for (const [key, val] of Object.entries(score.breakdown ?? {})) {
    const s   = val.score ?? 0;
    const cls = s >= 60 ? "high" : s >= 40 ? "mid" : "low";
    const w   = weights[key] ?? 0;
    html += `
      <div class="score-row">
        <span class="score-label">${key.toUpperCase()}</span>
        <div class="score-bar-wrap">
          <div class="score-bar ${cls}" style="width:${s}%"></div>
        </div>
        <span class="score-value">${s}</span>
        <span class="score-weight">${w}%</span>
        <span class="score-reason">${val.reason ?? ""}</span>
      </div>`;
  }

  // Progressione score
  const steps = score.score_steps ?? [];
  if (steps.length > 1) {
    html += `<div style="margin-top:14px;padding-top:12px;border-top:1px solid var(--border)">
      <div style="font-size:0.65rem;color:var(--text-dim);text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px">Progressione Score</div>`;
    for (let i = 0; i < steps.length; i++) {
      const step  = steps[i];
      const isLast= i === steps.length - 1;
      const dCol  = step.delta == null ? "var(--text-dim)"
                  : step.delta > 0 ? "var(--green)"
                  : step.delta < 0 ? "var(--red)"
                  : "var(--text-dim)";
      const dStr  = step.delta == null ? ""
                  : step.delta > 0 ? ` (+${step.delta})`
                  : ` (${step.delta})`;
      html += `
        <div style="display:flex;justify-content:space-between;align-items:center;
                    padding:5px 8px;border-radius:4px;margin-bottom:2px;
                    background:${isLast ? "var(--bg3)" : "transparent"}">
          <span style="font-size:0.72rem;color:${isLast ? "var(--text)" : "var(--text-dim)"}">
            ${i === 0 ? "▸" : "→"} ${step.label}
          </span>
          <span style="font-size:${isLast ? "1rem" : "0.78rem"};
                       font-weight:${isLast ? "800" : "400"};
                       font-family:${isLast ? "var(--sans)" : "var(--mono)"};
                       color:${isLast ? (score.signal==="BUY"?"var(--green)":score.signal==="WATCH"?"var(--yellow)":"var(--red)") : dCol}">
            ${step.value}<span style="font-size:0.65rem;color:var(--text-dim)">/100</span>
            <span style="font-size:0.7rem;color:${dCol}">${dStr}</span>
          </span>
        </div>`;
    }
    html += `</div>`;
  }

  // Badge segnale finale
  const sig    = score.signal;
  const sigCls = sig === "BUY" ? "buy" : sig === "WATCH" ? "watch" : "skip";
  html += `
    <div class="total-score">
      <span class="label">Score Finale</span>
      <span class="num ${sigCls}">${score.score}/100</span>
    </div>`;

  // Hard block
  if (score.block_reason) {
    html += `<div style="margin-top:8px;padding:8px 12px;background:var(--red-dim);
      border:1px solid var(--red);border-radius:var(--radius);font-size:0.72rem;color:var(--red)">
      🚫 ${score.block_reason}</div>`;
  }

  return html;
}

// ─────────────────────────────────────────────────────────────────
// INDICATORS
// ─────────────────────────────────────────────────────────────────
function renderIndicators(ind, price) {
  const close = price?.price_usd ?? 0;

  const rsiSignal  = ind.rsi < 35 ? "bull" : ind.rsi > 65 ? "bear" : "neut";
  const rsiLabel   = ind.rsi < 35 ? "Oversold" : ind.rsi > 65 ? "Overbought" : "Neutro";
  const macdSignal = ind.macd_hist > 0 ? "bull" : "bear";
  const macdLabel  = ind.macd_hist > 0 ? "Momentum +" : "Momentum −";
  const adxSignal  = ind.adx > 25 ? "bull" : "neut";
  const adxLabel   = ind.adx > 25 ? "Trend forte" : "Laterale";
  const volSignal  = ind.volume_ratio > 1.5 ? "bull" : ind.volume_ratio < 0.8 ? "bear" : "neut";

  return `
    <div class="ind-grid">
      <div class="ind-cell">
        <div class="ic-label">RSI (14)</div>
        <div class="ic-val">${ind.rsi}</div>
        <span class="ic-signal ${rsiSignal}">${rsiLabel}</span>
      </div>
      <div class="ind-cell">
        <div class="ic-label">MACD Hist</div>
        <div class="ic-val">${ind.macd_hist}</div>
        <span class="ic-signal ${macdSignal}">${macdLabel}</span>
      </div>
      <div class="ind-cell">
        <div class="ic-label">ADX</div>
        <div class="ic-val">${ind.adx}</div>
        <span class="ic-signal ${adxSignal}">${adxLabel}</span>
      </div>
      <div class="ind-cell">
        <div class="ic-label">Volume Ratio</div>
        <div class="ic-val">${ind.volume_ratio}x</div>
        <span class="ic-signal ${volSignal}">${ind.volume_ratio > 1.5 ? "Surge" : ind.volume_ratio < 0.8 ? "Basso" : "Normale"}</span>
      </div>
      <div class="ind-cell">
        <div class="ic-label">ATR</div>
        <div class="ic-val">$${ind.atr}</div>
        <span class="ic-signal neut">${((ind.atr/close)*100).toFixed(1)}% del prezzo</span>
      </div>
      <div class="ind-cell">
        <div class="ic-label">BB Position</div>
        <div class="ic-val">${(ind.bb_position*100).toFixed(0)}%</div>
        <span class="ic-signal ${ind.bb_position<0.25?"bull":ind.bb_position>0.75?"bear":"neut"}">${ind.bb_position<0.25?"Near Lower":ind.bb_position>0.75?"Near Upper":"Centrale"}</span>
      </div>
      <div class="ind-cell">
        <div class="ic-label">MA20</div>
        <div class="ic-val">$${ind.ma20}</div>
        <span class="ic-signal ${close>ind.ma20?"bull":"bear"}">${close>ind.ma20?"Sopra":"Sotto"}</span>
      </div>
      <div class="ind-cell">
        <div class="ic-label">MA50</div>
        <div class="ic-val">$${ind.ma50}</div>
        <span class="ic-signal ${close>ind.ma50?"bull":"bear"}">${close>ind.ma50?"Sopra":"Sotto"}</span>
      </div>
    </div>`;
}

// ─────────────────────────────────────────────────────────────────
// KEY LEVELS
// ─────────────────────────────────────────────────────────────────
function renderKeyLevels(levels, close) {
  if (!levels) return "<p style='color:var(--text-dim)'>N/A</p>";
  let html = '<div class="levels-grid">';
  const names = {
    recent_high:"Max 60gg", recent_low:"Min 60gg",
    ma20:"MA20", ma50:"MA50", ma200:"MA200",
    bb_upper:"BB Upper", bb_lower:"BB Lower"
  };
  for (const [k, v] of Object.entries(levels)) {
    const up = v.dist_pct >= 0;
    html += `
      <div class="level-row">
        <span class="lname">${names[k]??k}</span>
        <span class="lprice">$${v.price}</span>
        <span class="ldist ${up?"up":"down"}">${up?"+":""}${v.dist_pct}%</span>
      </div>`;
  }
  html += "</div>";
  return html;
}

// ─────────────────────────────────────────────────────────────────
// TRADE PANEL
// ─────────────────────────────────────────────────────────────────
function renderTradePanel(sig, signalType) {
  if (signalType !== "BUY") {
    return `
      <div class="card">
        <div class="card-body" style="text-align:center;padding:30px;color:var(--text-dim)">
          <div style="font-size:2rem;margin-bottom:10px">◉</div>
          <div style="font-family:var(--sans);font-size:1rem;color:var(--yellow)">Nessun segnale BUY attivo</div>
          <div style="margin-top:8px;font-size:0.8rem">Score attuale insufficiente per entrare.<br>
          Monitora i prossimi giorni.</div>
          ${sig?.signal ? `<div style="margin-top:16px;font-size:0.75rem;color:var(--text-dim)">${sig.explanation??""}</div>` : ""}
        </div>
      </div>`;
  }

  const rr = sig.risk_reward ?? 0;
  const sizeFactor = sig.size_factor ?? 1.0;
  const isOverext  = sizeFactor < 1.0;
  const overextBanner = isOverext ? `
    <div style="background:rgba(255,180,0,0.10);border:1px solid var(--yellow);border-radius:6px;
                padding:10px 14px;margin-bottom:12px;font-size:0.8rem;display:flex;gap:10px;align-items:center">
      <span style="font-size:1.2rem">⚡</span>
      <div>
        <div style="color:var(--yellow);font-weight:700;margin-bottom:2px">Setup esaurito — Size ridotta al 50%</div>
        <div style="color:var(--text-dim)">RSI o BB in zona overbought. Il segnale è valido ma il setup è avanzato.
        Il sistema entra con rischio <strong>1%</strong> invece del 2% per ridurre l'esposizione.</div>
      </div>
    </div>` : "";

  return `
    <div class="card">
      <div class="card-header">Operazione Proposta</div>
      <div class="card-body">
        ${overextBanner}
        <div class="trade-grid">
          <div class="trade-cell entry">
            <div class="tc-label">Ingresso</div>
            <div class="tc-val">€${sig.entry_eur}</div>
            <div class="tc-sub">$${sig.entry_usd}</div>
          </div>
          <div class="trade-cell sl">
            <div class="tc-label">Stop Loss</div>
            <div class="tc-val">€${sig.stop_loss_eur}</div>
            <div class="tc-sub">-${sig.pct_to_sl}%</div>
          </div>
          <div class="trade-cell target">
            <div class="tc-label">Target</div>
            <div class="tc-val">€${sig.target_eur}</div>
            <div class="tc-sub">+${sig.pct_to_target}%</div>
          </div>
        </div>

        <div class="trade-grid" style="margin-top:10px">
          <div class="trade-cell">
            <div class="tc-label">Risk/Reward</div>
            <div class="tc-val" style="color:${rr>=1.5?'var(--green)':'var(--yellow)'}">${rr}:1</div>
            <div class="tc-sub">${rr>=1.5?"✅ Buono":"⚠️ Basso"}</div>
          </div>
          <div class="trade-cell">
            <div class="tc-label">Azioni</div>
            <div class="tc-val">${sig.shares}</div>
            <div class="tc-sub">€${sig.invested_eur} investito</div>
          </div>
          <div class="trade-cell">
            <div class="tc-label">Max Perdita</div>
            <div class="tc-val" style="color:var(--red)">-€${sig.max_loss_eur}</div>
            <div class="tc-sub" style="color:${isOverext?'var(--yellow)':''}">
              ${isOverext ? "⚡ 1% (size ridotta)" : "2% del capitale"}
            </div>
          </div>
        </div>

        <div style="margin:14px 0;display:flex;gap:8px;font-size:0.75rem">
          <div style="flex:1;background:var(--bg3);border-radius:6px;padding:10px">
            <div style="color:var(--text-dim);margin-bottom:4px">⏱ Tempo stimato</div>
            <div style="color:var(--text-bright);font-weight:700">${sig.holding_days?.label ?? "—"}</div>
          </div>
          <div style="flex:1;background:var(--bg3);border-radius:6px;padding:10px">
            <div style="color:var(--text-dim);margin-bottom:4px">🕯 Candela</div>
            <div style="color:var(--text-bright);font-weight:700">${sig.candle_pattern ?? "—"}</div>
          </div>
        </div>

        <div class="trade-instructions">
          <strong>📋 Istruzioni per Trade Republic:</strong>
          <ol>
            <li>Apri l'app e cerca: <strong>${sig.ticker}</strong></li>
            <li>Premi "Compra" → scegli <strong>Ordine Limit</strong> a €${sig.entry_eur}</li>
            <li>Quantità: <strong>${sig.shares} azioni</strong></li>
            <li>Dopo l'esecuzione imposta <strong>Stop Loss a €${sig.stop_loss_eur}</strong></li>
            <li>Imposta <strong>Limit di vendita a €${sig.target_eur}</strong></li>
          </ol>
        </div>
      </div>
    </div>`;
}

// ─────────────────────────────────────────────────────────────────
// NEWS PANEL
// ─────────────────────────────────────────────────────────────────
function renderNewsPanel(sentiment) {
  const { fear_greed, vix, news, sentiment_score, sentiment_label } = sentiment ?? {};
  const fg  = fear_greed ?? {};
  const vixD = vix ?? {};
  const articles = news?.articles ?? [];

  let html = `
    <div class="sentiment-row" style="margin-bottom:16px">
      <div class="sent-block">
        <div class="sb-label">VIX</div>
        <div class="sb-val" style="color:${vixD.value>30?'var(--red)':vixD.value>20?'var(--yellow)':'var(--green)'}">${vixD.value?.toFixed(1) ?? "—"}</div>
        <div class="sb-desc">${vixD.signal ?? ""}</div>
      </div>
      <div class="sent-block">
        <div class="sb-label">Fear & Greed</div>
        <div class="sb-val" style="color:${fg.value<30?'var(--red)':fg.value>70?'var(--yellow)':'var(--text-bright)'}">${fg.value ?? "—"}/100</div>
        <div class="sb-desc">${fg.classification ?? ""}</div>
      </div>
      <div class="sent-block">
        <div class="sb-label">Sentiment Score</div>
        <div class="sb-val" style="color:${sentiment_score>10?'var(--green)':sentiment_score<-10?'var(--red)':'var(--text-bright)'}">${sentiment_score > 0 ? "+" : ""}${sentiment_score ?? 0}</div>
        <div class="sb-desc">${sentiment_label ?? ""}</div>
      </div>
      <div class="sent-block">
        <div class="sb-label">Notizie</div>
        <div class="sb-val">${news?.count ?? 0}</div>
        <div class="sb-desc">ultime 48h</div>
      </div>
    </div>
    <div class="card">
      <div class="card-header">Ultime Notizie</div>
      <div class="card-body">`;

  if (articles.length === 0) {
    html += `<p style="color:var(--text-dim);font-size:0.8rem">Nessuna notizia recente disponibile.</p>`;
  } else {
    for (const a of articles) {
      const cls = a.sentiment_score > 0 ? "bull" : a.sentiment_score < 0 ? "bear" : "neut";
      html += `
        <div class="news-item">
          <div class="news-dot ${cls}"></div>
          <div style="flex:1">
            <div class="news-title">${a.title}</div>
            <div class="news-time">${a.published}</div>
          </div>
        </div>`;
    }
  }

  html += `</div></div>`;
  return html;
}


// ─────────────────────────────────────────────────────────────────
// EARNINGS BANNER
// ─────────────────────────────────────────────────────────────────
function renderEarningsBanner(earnings) {
  if (!earnings || earnings.level === "none" || earnings.level === "info" || !earnings.banner) return "";

  const cfg = {
    block:  {
      bg:    "rgba(248,81,73,0.12)",
      border:"var(--red)",
      icon:  "🚨",
      title: "EARNINGS IMMINENTI — BUY BLOCCATO",
      tcol:  "var(--red)",
      note:  "Segnale BUY automaticamente bloccato. Attendi dopo la pubblicazione degli utili.",
    },
    orange: {
      bg:    "rgba(210,100,34,0.12)",
      border:"#e06020",
      icon:  "⚠️",
      title: "EARNINGS IN ARRIVO",
      tcol:  "#e07030",
      note:  `Score ridotto del ${earnings.penalty ?? 15}%. Rischio volatilità elevata post-earnings.`,
    },
    yellow: {
      bg:    "rgba(210,153,34,0.10)",
      border:"var(--yellow)",
      icon:  "📅",
      title: "EARNINGS NEI PROSSIMI 14 GIORNI",
      tcol:  "var(--yellow)",
      note:  `Score ridotto del ${earnings.penalty ?? 7}%. Considera l'impatto degli utili sulla posizione.`,
    },
  };

  const c = cfg[earnings.banner] || cfg.yellow;

  return `
    <div style="
      background: ${c.bg};
      border: 1px solid ${c.border};
      border-radius: var(--radius);
      padding: 12px 16px;
      display: flex; align-items: flex-start; gap: 12px;
      margin-bottom: 14px;
    ">
      <span style="font-size:1.4rem;margin-top:1px">${c.icon}</span>
      <div style="flex:1">
        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:6px">
          <strong style="color:${c.tcol};font-family:var(--sans);font-size:0.85rem">${c.title}</strong>
          <span style="background:var(--bg3);border:1px solid var(--border);border-radius:4px;
                       padding:2px 8px;font-size:0.72rem;color:var(--text-bright)">
            ${earnings.date ?? "data n.d."}
          </span>
        </div>
        <div style="margin-top:5px;font-size:0.75rem;color:var(--text-dim)">${c.note}</div>
        <div style="margin-top:3px;font-size:0.72rem;color:var(--text-dim)">${earnings.label ?? ""}</div>
      </div>
    </div>`;
}

// ─────────────────────────────────────────────────────────────────
// MULTI-TIMEFRAME
// ─────────────────────────────────────────────────────────────────
function renderMultiTimeframe(mtf) {
  if (!mtf) return "<p style='color:var(--text-dim)'>N/A</p>";

  const tfs = [
    { key: "weekly", label: "Weekly",  icon: "📅" },
    { key: "daily",  label: "Daily",   icon: "📆" },
    { key: "h4",     label: "4 Ore",   icon: "🕓" },
  ];

  const alignMap = {
    full_bullish:    { color: "var(--green)",  icon: "▲▲▲", label: "Pieno allineamento rialzista" },
    mostly_bullish:  { color: "var(--green)",  icon: "▲▲○", label: "Prevalentemente rialzista" },
    mostly_bearish:  { color: "var(--red)",    icon: "▼▼○", label: "Prevalentemente ribassista" },
    full_bearish:    { color: "var(--red)",    icon: "▼▼▼", label: "Pieno allineamento ribassista" },
    unknown:         { color: "var(--text-dim)", icon: "○○○", label: "Dati insufficienti" },
  };

  const align = alignMap[mtf.alignment] || alignMap.unknown;

  let html = `
    <div style="
      background:var(--bg3); border-radius:var(--radius);
      padding:10px 14px; margin-bottom:12px;
      display:flex; align-items:center; justify-content:space-between;
    ">
      <span style="font-size:1.2rem">${align.icon}</span>
      <span style="color:${align.color}; font-weight:700; font-size:0.85rem">${align.label}</span>
      <span style="color:var(--text-dim); font-size:0.7rem">${mtf.bullish_count ?? 0}/${mtf.total_tf ?? 3} bullish</span>
    </div>`;

  for (const { key, label, icon } of tfs) {
    const tf = mtf[key];
    if (!tf || tf.error) {
      html += `<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border);font-size:0.75rem">
        <span>${icon} ${label}</span><span style="color:var(--text-dim)">N/A</span></div>`;
      continue;
    }
    const bull = tf.trend?.includes("bull");
    const col  = bull ? "var(--green)" : "var(--red)";
    const arr  = bull ? "▲" : "▼";
    html += `
      <div style="display:flex;justify-content:space-between;align-items:center;padding:7px 0;border-bottom:1px solid var(--border);font-size:0.75rem">
        <span style="color:var(--text-dim)">${icon} ${label}</span>
        <div style="text-align:right">
          <span style="color:${col};font-weight:700">${arr} ${tf.trend?.replace("_"," ")?.toUpperCase()}</span>
          <span style="color:var(--text-dim);margin-left:8px">RSI ${tf.rsi}</span>
          <span style="color:var(--text-dim);margin-left:8px">EMA20 ${tf.above_ema20?"↑":"↓"}</span>
        </div>
      </div>`;
  }

  return html;
}

// ─────────────────────────────────────────────────────────────────
// RELATIVE STRENGTH
// ─────────────────────────────────────────────────────────────────
function renderRelativeStrength(rs) {
  if (!rs || rs.error) return "<p style='color:var(--text-dim)'>Dati non disponibili</p>";

  const positive = rs.rs >= 0;
  const col      = rs.rs >= 2  ? "var(--green)" :
                   rs.rs >= -2 ? "var(--text-bright)" :
                                 "var(--red)";
  const bar_w    = Math.min(Math.abs(rs.rs) * 5, 100);
  const bar_col  = positive ? "var(--green)" : "var(--red)";

  return `
    <div style="text-align:center; padding: 8px 0 16px">
      <div style="font-size:2rem; font-weight:800; color:${col}; font-family:var(--sans)">
        ${rs.rs >= 0 ? "+" : ""}${rs.rs}%
      </div>
      <div style="font-size:0.75rem; color:var(--text-dim); margin-top:2px">${rs.label}</div>
    </div>

    <div style="display:flex; align-items:center; gap:8px; margin-bottom:12px">
      <div style="flex:1; height:6px; background:var(--bg3); border-radius:3px; overflow:hidden">
        <div style="width:${bar_w}%; height:100%; background:${bar_col}; border-radius:3px;
                    margin-left:${positive ? '50%' : (50 - bar_w) + '%'}"></div>
      </div>
    </div>

    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; font-size:0.75rem">
      <div style="background:var(--bg3); border-radius:var(--radius); padding:8px; text-align:center">
        <div style="color:var(--text-dim); margin-bottom:3px">Ticker (${rs.days}gg)</div>
        <div style="font-weight:700; color:${rs.ticker_ret>=0?'var(--green)':'var(--red)'}">
          ${rs.ticker_ret >= 0 ? "+" : ""}${rs.ticker_ret}%
        </div>
      </div>
      <div style="background:var(--bg3); border-radius:var(--radius); padding:8px; text-align:center">
        <div style="color:var(--text-dim); margin-bottom:3px">S&P 500 (${rs.days}gg)</div>
        <div style="font-weight:700; color:${rs.sp500_ret>=0?'var(--green)':'var(--red)'}">
          ${rs.sp500_ret >= 0 ? "+" : ""}${rs.sp500_ret}%
        </div>
      </div>
    </div>`;
}

// ─────────────────────────────────────────────────────────────────
// BACKTEST
// ─────────────────────────────────────────────────────────────────

// ─────────────────────────────────────────────────────────────────
// AI ANALYST
// ─────────────────────────────────────────────────────────────────

async function loadAI(ticker) {
  const body = document.getElementById("ai-body");
  const btn  = document.getElementById("ai-btn");
  if (!body || !ticker) return;

  btn.textContent = "⏳ Analizzando...";
  btn.disabled    = true;
  body.innerHTML  = '<div style="display:flex;align-items:center;gap:12px;padding:12px 0;color:var(--text-dim);font-size:0.8rem">'
    + '<div class="spinner" style="width:18px;height:18px;border:2px solid var(--border);'
    + 'border-top-color:var(--accent);border-radius:50%;animation:spin 0.8s linear infinite"></div>'
    + 'Interrogo llama-3.3-70b con tutti i dati di ' + ticker + '...</div>';

  try {
    const d = await fetchJSON("/api/ai/" + ticker);
    body.innerHTML  = renderAIAnalysis(d.analysis);
    btn.textContent = "🔄 Rianalizza";
    btn.disabled    = false;
  } catch(e) {
    body.innerHTML  = '<p style="color:var(--red)">Errore: ' + e.message + '. Verifica GROQ_API_KEY nel file .env</p>';
    btn.textContent = "▶ Riprova";
    btn.disabled    = false;
  }
}

function renderAIAnalysis(a) {
  if (!a) return "<p style='color:var(--red)'>Analisi non disponibile</p>";

  const vMap = {
    "COMPRA ORA":  { col: "var(--green)",  bg: "rgba(35,134,54,0.12)",  icon: "🟢" },
    "ASPETTA":     { col: "var(--yellow)", bg: "rgba(210,153,34,0.12)", icon: "🟡" },
    "NON ENTRARE": { col: "var(--red)",    bg: "rgba(248,81,73,0.12)",  icon: "🔴" },
  };
  const cMap = { alta: "var(--green)", media: "var(--yellow)", bassa: "var(--red)" };
  const v    = vMap[a.verdict] || vMap["ASPETTA"];
  const cCol = cMap[a.confidence] || "var(--text-dim)";

  let html = "";

  // Verdetto
  html += '<div style="background:' + v.bg + ';border:1px solid ' + v.col + ';border-radius:var(--radius);'
        + 'padding:14px 18px;margin-bottom:14px;display:flex;align-items:center;gap:14px">'
        + '<span style="font-size:2rem">' + v.icon + '</span>'
        + '<div><div style="font-size:1.1rem;font-weight:800;color:' + v.col + ';font-family:var(--sans)">' + a.verdict + '</div>'
        + '<div style="font-size:0.72rem;color:var(--text-dim);margin-top:2px">Confidenza: '
        + '<span style="color:' + cCol + ';font-weight:600">' + (a.confidence||"").toUpperCase() + '</span></div>'
        + '</div></div>';

  // Ragionamento
  html += '<div style="margin-bottom:12px">'
        + '<div style="font-size:0.65rem;color:var(--text-dim);text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px">Ragionamento</div>'
        + '<p style="font-size:0.8rem;line-height:1.7;color:var(--text);margin:0">' + (a.reasoning||"") + '</p></div>';

  // Rischi
  html += '<div style="background:rgba(248,81,73,0.07);border-left:3px solid var(--red);'
        + 'padding:10px 14px;border-radius:0 var(--radius) var(--radius) 0;margin-bottom:12px">'
        + '<div style="font-size:0.65rem;color:var(--red);text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px">Rischi</div>'
        + '<p style="font-size:0.78rem;line-height:1.6;color:var(--text-dim);margin:0">' + (a.risk_notes||"") + '</p></div>';

  // Scenari
  html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">'
        + '<div style="background:rgba(35,134,54,0.08);border:1px solid rgba(35,134,54,0.3);border-radius:var(--radius);padding:10px 12px">'
        + '<div style="font-size:0.65rem;color:var(--green);text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px">Scenario ottimistico</div>'
        + '<p style="font-size:0.75rem;line-height:1.5;color:var(--text-dim);margin:0">' + (a.best_case||"") + '</p></div>'
        + '<div style="background:rgba(248,81,73,0.08);border:1px solid rgba(248,81,73,0.3);border-radius:var(--radius);padding:10px 12px">'
        + '<div style="font-size:0.65rem;color:var(--red);text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px">Scenario pessimistico</div>'
        + '<p style="font-size:0.75rem;line-height:1.5;color:var(--text-dim);margin:0">' + (a.worst_case||"") + '</p></div></div>';

  html += '<div style="margin-top:10px;font-size:0.65rem;color:var(--text-dim);text-align:right">Modello: llama-3.3-70b-versatile via Groq</div>';
  return html;
}



// ─────────────────────────────────────────────────────────────────
// BACKTEST TUTTO — riepilogo completo per settore
// ─────────────────────────────────────────────────────────────────

async function showBacktestAll() {
  // Nascondi altri pannelli, mostra quello di backtest
  document.getElementById("welcome").style.display       = "none";
  document.getElementById("ticker-view").style.display   = "none";
  const panel = document.getElementById("backtest-all-panel");
  panel.style.display = "block";

  panel.innerHTML = `
    <div style="display:flex;align-items:center;gap:14px;margin-bottom:20px">
      <h2 style="margin:0;font-family:var(--sans);font-size:1.1rem">📊 Backtest Completo — 2 anni</h2>
      <span style="color:var(--text-dim);font-size:0.78rem">VIX=20, F&G=50 (condizioni neutre)</span>
    </div>
    <div style="display:flex;align-items:center;gap:12px;color:var(--text-dim);font-size:0.82rem">
      <div class="spinner" style="width:18px;height:18px;border:2px solid var(--border);
           border-top-color:var(--accent);border-radius:50%;animation:spin 0.8s linear infinite;flex-shrink:0"></div>
      Esecuzione backtest su ${window.WATCHLIST ? Object.values(window.WATCHLIST).flat().length : 18} ticker... può richiedere 1-2 minuti
    </div>`;

  try {
    const d = await fetchJSON("/api/backtest_all");
    panel.innerHTML = renderBacktestAll(d);
  } catch(e) {
    panel.innerHTML = `<p style="color:var(--red)">Errore: ${e.message}</p>`;
  }
}

function renderBacktestAll(d) {
  const a   = d.aggregate    || {};
  const bys = d.by_sector    || {};
  const byt = d.by_ticker    || [];

  const retCol  = a.avg_return_pct >= 0 ? "var(--green)" : "var(--red)";
  const pfGood  = a.profit_factor  >= 1.5;
  const wrGood  = a.win_rate       >= 50;

  // ── Riepilogo aggregato ────────────────────────────────────────
  let html = `
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;flex-wrap:wrap;gap:8px">
    <h2 style="margin:0;font-family:var(--sans);font-size:1.1rem">📊 Backtest Completo — 2 anni</h2>
    <button onclick="showBacktestAll()" style="background:var(--bg3);border:1px solid var(--border);
      color:var(--text-dim);padding:5px 12px;border-radius:4px;cursor:pointer;font-size:0.72rem">
      🔄 Riesegui
    </button>
  </div>

  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:24px">
    ${statCard("Ticker analizzati", a.total_tickers, "var(--text-bright)")}
    ${statCard("Trade totali", a.total_trades, "var(--text-bright)")}
    ${statCard("Win Rate", a.win_rate + "%", wrGood ? "var(--green)" : "var(--red)")}
    ${statCard("Profit Factor", a.profit_factor, pfGood ? "var(--green)" : "var(--yellow)")}
    ${statCard("P&L totale", "€" + a.total_pnl_eur, a.total_pnl_eur >= 0 ? "var(--green)" : "var(--red)")}
    ${statCard("Rendimento medio/ticker", (a.avg_return_pct >= 0 ? "+" : "") + a.avg_return_pct + "%", retCol)}
    ${statCard("P&L medio/trade", "€" + a.avg_pnl_per_trade, a.avg_pnl_per_trade >= 0 ? "var(--green)" : "var(--red)")}
    ${statCard("Capitale iniziale/ticker", "€" + a.initial_capital, "var(--text-dim)")}
  </div>

  <!-- Exit type distribution -->
  <div class="card" style="margin-bottom:20px">
    <div class="card-header">Distribuzione Uscite (tutti i ticker)</div>
    <div class="card-body" style="display:flex;gap:16px;flex-wrap:wrap">
      ${Object.entries(a.exit_types || {}).map(([k,v]) => {
        const col = k==="TARGET"?"var(--green)":k==="STOP_LOSS"?"var(--red)":"var(--text-dim)";
        const pct = Math.round(v / a.total_trades * 100);
        return `<div style="text-align:center;padding:8px 16px;background:var(--bg3);border-radius:var(--radius)">
          <div style="font-size:1.2rem;font-weight:800;color:${col};font-family:var(--sans)">${pct}%</div>
          <div style="font-size:0.68rem;color:var(--text-dim);margin-top:2px">${k.replace("_"," ")}</div>
          <div style="font-size:0.65rem;color:var(--text-dim)">${v} trade</div>
        </div>`;
      }).join("")}
    </div>
  </div>`;

  // ── Tabella per settore ────────────────────────────────────────
  html += `<div class="card" style="margin-bottom:20px">
    <div class="card-header">Riepilogo per Settore</div>
    <div class="card-body" style="padding:0">
    <table style="width:100%;border-collapse:collapse;font-size:0.78rem">
      <thead>
        <tr style="color:var(--text-dim);font-size:0.65rem;text-transform:uppercase;letter-spacing:.06em">
          <th style="padding:10px 16px;text-align:left;border-bottom:1px solid var(--border)">Settore</th>
          <th style="padding:10px 12px;text-align:center;border-bottom:1px solid var(--border)">Trade</th>
          <th style="padding:10px 12px;text-align:center;border-bottom:1px solid var(--border)">Win Rate</th>
          <th style="padding:10px 12px;text-align:right;border-bottom:1px solid var(--border)">P&L totale</th>
          <th style="padding:10px 12px;text-align:right;border-bottom:1px solid var(--border)">Rendimento medio</th>
        </tr>
      </thead>
      <tbody>`;

  const sectorsSorted = Object.entries(bys).sort((a,b) => b[1].total_pnl_eur - a[1].total_pnl_eur);
  for (const [sector, s] of sectorsSorted) {
    const wrCol  = s.win_rate >= 50 ? "var(--green)" : s.win_rate >= 40 ? "var(--yellow)" : "var(--red)";
    const pnlCol = s.total_pnl_eur >= 0 ? "var(--green)" : "var(--red)";
    const retCol = s.avg_return_pct >= 0 ? "var(--green)" : "var(--red)";
    html += `
      <tr style="border-bottom:1px solid var(--border)">
        <td style="padding:10px 16px;color:var(--text-bright);font-weight:600">${sector}
          <span style="color:var(--text-dim);font-weight:400;font-size:0.7rem"> — ${s.tickers.join(", ")}</span>
        </td>
        <td style="padding:10px 12px;text-align:center">${s.total_trades}</td>
        <td style="padding:10px 12px;text-align:center;color:${wrCol};font-weight:700">${s.win_rate}%</td>
        <td style="padding:10px 12px;text-align:right;color:${pnlCol};font-weight:700">€${s.total_pnl_eur >= 0 ? "+" : ""}${s.total_pnl_eur}</td>
        <td style="padding:10px 12px;text-align:right;color:${retCol}">${s.avg_return_pct >= 0 ? "+" : ""}${s.avg_return_pct}%</td>
      </tr>`;
  }
  html += `</tbody></table></div></div>`;

  // ── Classifica ticker ─────────────────────────────────────────
  html += `<div class="card">
    <div class="card-header">Classifica Ticker — dal migliore al peggiore</div>
    <div class="card-body" style="padding:0">
    <table style="width:100%;border-collapse:collapse;font-size:0.78rem">
      <thead>
        <tr style="color:var(--text-dim);font-size:0.65rem;text-transform:uppercase;letter-spacing:.06em">
          <th style="padding:10px 16px;text-align:left;border-bottom:1px solid var(--border)">#</th>
          <th style="padding:10px 12px;text-align:left;border-bottom:1px solid var(--border)">Ticker</th>
          <th style="padding:10px 12px;text-align:center;border-bottom:1px solid var(--border)">Trade</th>
          <th style="padding:10px 12px;text-align:center;border-bottom:1px solid var(--border)">Win%</th>
          <th style="padding:10px 12px;text-align:right;border-bottom:1px solid var(--border)">Rendimento</th>
          <th style="padding:10px 12px;text-align:right;border-bottom:1px solid var(--border)">Profit Factor</th>
          <th style="padding:10px 12px;text-align:right;border-bottom:1px solid var(--border)">Max DD</th>
          <th style="padding:10px 12px;text-align:right;border-bottom:1px solid var(--border)">Freq.</th>
        </tr>
      </thead>
      <tbody>`;

  for (let i = 0; i < byt.length; i++) {
    const r      = byt[i];
    const retC   = r.total_return  >= 0 ? "var(--green)" : "var(--red)";
    const wrC    = r.win_rate      >= 50 ? "var(--green)" : r.win_rate >= 40 ? "var(--yellow)" : "var(--red)";
    const pfC    = r.profit_factor >= 1.5 ? "var(--green)" : r.profit_factor >= 1.0 ? "var(--yellow)" : "var(--red)";
    const medal  = i === 0 ? "🥇" : i === 1 ? "🥈" : i === 2 ? "🥉" : (i+1);
    html += `
      <tr style="border-bottom:1px solid var(--border);cursor:pointer"
          onclick="loadTicker('${r.ticker}');document.getElementById('backtest-all-panel').style.display='none';document.getElementById('ticker-view').style.display='block'">
        <td style="padding:10px 16px;color:var(--text-dim)">${medal}</td>
        <td style="padding:10px 12px;font-weight:700;color:var(--text-bright);font-family:var(--sans)">${r.ticker}</td>
        <td style="padding:10px 12px;text-align:center">${r.total_trades}</td>
        <td style="padding:10px 12px;text-align:center;color:${wrC};font-weight:600">${r.win_rate}%</td>
        <td style="padding:10px 12px;text-align:right;color:${retC};font-weight:700">${r.total_return >= 0 ? "+" : ""}${r.total_return}%</td>
        <td style="padding:10px 12px;text-align:right;color:${pfC}">${r.profit_factor}</td>
        <td style="padding:10px 12px;text-align:right;color:var(--red)">-${r.max_drawdown}%</td>
        <td style="padding:10px 12px;text-align:right;color:var(--text-dim);font-size:0.7rem">${r.signal_frequency || "—"}</td>
      </tr>`;
  }
  html += `</tbody></table></div></div>`;

  return html;
}

function statCard(label, value, col) {
  return `<div style="background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:14px 16px">
    <div style="font-size:1.1rem;font-weight:800;color:${col};font-family:var(--sans)">${value}</div>
    <div style="font-size:0.68rem;color:var(--text-dim);margin-top:4px">${label}</div>
  </div>`;
}

function renderSignalStats(stats) {
  if (!stats || Object.keys(stats).length === 0) return "";
  const entries = Object.entries(stats).sort((a,b) => b[1]-a[1]).slice(0, 6);
  const total   = entries.reduce((s, [,v]) => s + v, 0);
  let html = '<div style="margin-top:8px;padding-top:8px;border-top:1px solid rgba(255,255,255,0.08)">'
           + '<span style="color:var(--text-dim);font-size:0.68rem">Segnali filtrati (' + total + ' giorni): </span>';
  for (const [reason, count] of entries) {
    const pct = (count/total*100).toFixed(0);
    html += '<span style="background:var(--bg3);border-radius:3px;padding:1px 6px;margin:0 3px;font-size:0.68rem;color:var(--text-dim)">'
          + reason + ' <strong style="color:var(--text)">' + pct + '%</strong></span>';
  }
  return html + '</div>';
}

async function loadBacktest(ticker) {
  const el = document.getElementById("backtest-result");
  el.innerHTML = `<div style="text-align:center;padding:20px"><div class="spinner"></div><p style="margin-top:10px;color:var(--text-dim)">Backtest in corso…</p></div>`;

  try {
    const r = await fetchJSON(`/api/backtest/${ticker}`);
    el.innerHTML = renderBacktestResult(r);
  } catch(e) {
    el.innerHTML = `<div style="color:var(--red);padding:16px">Errore: ${e.message}</div>`;
  }
}

function renderBacktestResult(r) {
  if (r.error && r.total_trades === 0) {
    return `<div class="card"><div class="card-body" style="color:var(--text-dim)">${r.error}</div></div>`;
  }
  const retCls = r.total_return >= 0 ? "pos" : "neg";
  const retSign= r.total_return >= 0 ? "+" : "";
  const pfGood = r.profit_factor >= 1.3;

  let html = `
    <div class="card" style="margin-top:16px">
      <div class="card-header">Backtest ${r.ticker} — 2 anni</div>
      <div class="card-body">

        <div style="background:var(--blue-dim);border:1px solid var(--accent);border-radius:var(--radius);
                    padding:10px 14px;margin-bottom:14px;font-size:0.75rem;line-height:1.8">
          <strong style="color:var(--blue)">ℹ️ Come leggere il backtest</strong><br>
          Il backtest simula solo i segnali <strong>BUY ≥ ${r.buy_threshold_used ?? 57}/100</strong> generati in condizioni neutre (VIX=20, F&G=50).
          Frequenza storica: <strong style="color:var(--text)">${r.signal_frequency ?? "N/A"}</strong>
          ${renderSignalStats(r.signal_stats)}
        </div>

        <div class="bt-stats">
          <div class="bt-stat"><div class="bs-label">Rendimento</div><div class="bs-val ${retCls}">${retSign}${r.total_return}%</div></div>
          <div class="bt-stat"><div class="bs-label">Capitale finale</div><div class="bs-val ${retCls}">€${r.final_capital}</div></div>
          <div class="bt-stat"><div class="bs-label">Win Rate</div><div class="bs-val ${r.win_rate>=50?'pos':'neg'}">${r.win_rate}%</div></div>
          <div class="bt-stat"><div class="bs-label">Profit Factor</div><div class="bs-val ${pfGood?'pos':'neg'}">${r.profit_factor} ${pfGood?"✅":"⚠️"}</div></div>
          <div class="bt-stat"><div class="bs-label">Max Drawdown</div><div class="bs-val neg">-${r.max_drawdown}%</div></div>
          <div class="bt-stat"><div class="bs-label">Totale Trade</div><div class="bs-val">${r.total_trades}</div></div>
          <div class="bt-stat"><div class="bs-label">P&L medio</div><div class="bs-val ${r.avg_pnl>=0?'pos':'neg'}">€${r.avg_pnl}</div></div>
          <div class="bt-stat"><div class="bs-label">Frequenza</div><div class="bs-val">${r.signal_frequency ?? "—"}</div></div>
        </div>

        <div class="card-header" style="margin-bottom:10px">Ultimi Trade</div>
        <div style="overflow-x:auto">
          <div class="bt-trade-row" style="color:var(--text-dim);font-size:0.65rem;border-bottom:1px solid var(--border2)">
            <span>Ingresso</span><span>Uscita</span><span>Entry $</span><span>Exit $</span><span>P&L €</span><span>Tipo uscita</span><span>Score</span>
          </div>`;

  for (const t of (r.trades ?? []).slice(-15).reverse()) {
    html += `
      <div class="bt-trade-row ${t.win?'win':'loss'}">
        <span>${t.entry_date}</span>
        <span>${t.exit_date}</span>
        <span>$${t.entry_usd}</span>
        <span>$${t.exit_usd}</span>
        <span class="bt-pnl">€${t.pnl_eur > 0 ? '+' : ''}${t.pnl_eur}</span>
        <span class="bt-exit">${t.exit_type}</span>
        <span>${t.score}</span>
      </div>`;
  }

  html += `</div></div></div>`;
  return html;
}

// ─────────────────────────────────────────────────────────────────
// CHARTS (Chart.js)
// ─────────────────────────────────────────────────────────────────
function renderCharts(cd, currentPrice) {
  if (!cd || !window.Chart) return;

  destroyCharts();

  const labels = cd.dates;

  // Price + BB
  const ctx1 = document.getElementById("chart-price");
  if (ctx1) {
    charts.price = new Chart(ctx1, {
      type: "line",
      data: {
        labels,
        datasets: [
          { label:"Close", data:cd.close, borderColor:"#58a6ff", borderWidth:1.5, pointRadius:0, fill:false, tension:0.3 },
          { label:"BB Upper", data:cd.bb_upper, borderColor:"rgba(248,81,73,0.4)", borderWidth:1, pointRadius:0, borderDash:[4,4], fill:false },
          { label:"BB Mid",   data:cd.bb_mid,   borderColor:"rgba(210,153,34,0.4)", borderWidth:1, pointRadius:0, borderDash:[2,4], fill:false },
          { label:"BB Lower", data:cd.bb_lower, borderColor:"rgba(63,185,80,0.4)",  borderWidth:1, pointRadius:0, borderDash:[4,4], fill:false },
          { label:"MA20", data:cd.ma20, borderColor:"rgba(57,208,216,0.6)", borderWidth:1, pointRadius:0, fill:false },
          { label:"MA50", data:cd.ma50, borderColor:"rgba(139,148,158,0.5)", borderWidth:1, pointRadius:0, fill:false },
        ]
      },
      options: chartOpts("$"),
    });
  }

  // RSI
  const ctx2 = document.getElementById("chart-rsi");
  if (ctx2) {
    charts.rsi = new Chart(ctx2, {
      type: "line",
      data: {
        labels,
        datasets: [
          { label:"RSI", data:cd.rsi, borderColor:"#d29922", borderWidth:1.5, pointRadius:0, fill:false, tension:0.3 },
        ]
      },
      options: {
        ...chartOpts(""),
        plugins: { legend:{ display:false }, tooltip:{ enabled:true } },
        scales: {
          x: xScale(),
          y: { min:0, max:100, grid:{ color:"rgba(30,45,61,0.6)" }, ticks:{ color:"#6e7f8d", font:{size:10} },
               afterDataLimits: s => { s.min=0; s.max=100; } }
        }
      }
    });
    // Linee RSI 35/65
    addRsiLines(ctx2);
  }

  // MACD
  const ctx3 = document.getElementById("chart-macd");
  if (ctx3) {
    charts.macd = new Chart(ctx3, {
      type: "bar",
      data: {
        labels,
        datasets: [
          { label:"Histogram", data:cd.macd_hist,
            backgroundColor: cd.macd_hist.map(v => v >= 0 ? "rgba(63,185,80,0.5)" : "rgba(248,81,73,0.5)"),
            borderWidth:0 },
          { label:"MACD",   data:cd.macd,    type:"line", borderColor:"#58a6ff", borderWidth:1.5, pointRadius:0, fill:false },
          { label:"Signal", data:cd.macd_sig, type:"line", borderColor:"#f85149", borderWidth:1, pointRadius:0, fill:false },
        ]
      },
      options: chartOpts(""),
    });
  }
}

function chartOpts(unit) {
  return {
    responsive: true, maintainAspectRatio: false,
    animation: { duration: 400 },
    interaction: { mode:"index", intersect:false },
    plugins: {
      legend: { display:true, labels:{ color:"#6e7f8d", font:{size:10}, boxWidth:12 } },
      tooltip: { enabled:true, backgroundColor:"#0d1117", borderColor:"#1e2d3d", borderWidth:1 }
    },
    scales: {
      x: xScale(),
      y: { grid:{ color:"rgba(30,45,61,0.6)" }, ticks:{ color:"#6e7f8d", font:{size:10}, callback: v => unit + v } }
    }
  };
}

function xScale() {
  return {
    grid: { color:"rgba(30,45,61,0.4)" },
    ticks: { color:"#6e7f8d", font:{size:9}, maxTicksLimit:8,
             maxRotation:0, callback: (_, i, arr) => {
               if (i === 0 || i === arr.length-1 || i % Math.floor(arr.length/6) === 0)
                 return arr[i]?.label?.slice(5) ?? ""; // MM-DD
               return "";
             }}
  };
}

function addRsiLines(ctx) {
  // Disegna linee orizzontali a 35 e 65 dopo il render
  Chart.register({
    id: "rsi-lines",
    afterDraw(chart) {
      if (chart.canvas.id !== "chart-rsi") return;
      const { ctx, chartArea: {left,right}, scales:{y} } = chart;
      [35, 65].forEach(val => {
        const yPos = y.getPixelForValue(val);
        ctx.save();
        ctx.strokeStyle = val === 35 ? "rgba(63,185,80,0.4)" : "rgba(248,81,73,0.4)";
        ctx.setLineDash([4, 4]);
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(left, yPos); ctx.lineTo(right, yPos);
        ctx.stroke();
        ctx.restore();
      });
    }
  });
}

function destroyCharts() {
  for (const c of Object.values(charts)) c?.destroy();
  charts = {};
}

// ─────────────────────────────────────────────────────────────────
// TABS
// ─────────────────────────────────────────────────────────────────
function setupTabs() {
  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const tabId = btn.dataset.tab;
      const container = btn.closest("div")?.parentElement;
      if (!container) return;

      container.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      container.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));

      btn.classList.add("active");
      const panel = container.querySelector(`#tab-${tabId}`);
      if (panel) panel.classList.add("active");

      // Ricarica grafici se si apre il tab charts
      if (tabId === "charts") {
        setTimeout(() => { for (const c of Object.values(charts)) c?.resize(); }, 50);
      }
    });
  });
}

// ─────────────────────────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────────────────────────
async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

function setEl(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function showLoading(msg) {
  const ov = document.getElementById("loading-overlay");
  if (ov) {
    ov.querySelector("p").textContent = msg ?? "Caricamento…";
    ov.classList.add("show");
  }
}

function hideLoading() {
  const ov = document.getElementById("loading-overlay");
  if (ov) ov.classList.remove("show");
}
