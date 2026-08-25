(() => {
  "use strict";

  const SIGNALS_REFRESH_MS = 5_000;

  const state = {
    intervalo: "1h",
    signalType: "",
    signalLevel: "",
    selectedSymbol: null,
    selectedRecord: null,
    records: [],
    signalsLoading: false,
    suggestionsTimer: null,
  };

  const elements = {
    connection: document.querySelector("#connection-status"),
    timeframes: document.querySelector("#timeframes"),
    type: document.querySelector("#signal-type"),
    level: document.querySelector("#signal-level"),
    refresh: document.querySelector("#refresh"),
    search: document.querySelector("#symbol-search"),
    form: document.querySelector("#search-form"),
    suggestions: document.querySelector("#symbol-suggestions"),
    body: document.querySelector("#signals-body"),
    empty: document.querySelector("#empty-state"),
    tableStatus: document.querySelector("#table-status"),
    metricTotal: document.querySelector("#metric-total"),
    metricTotalCaption: document.querySelector("#metric-total-caption"),
    metricOverbought: document.querySelector("#metric-overbought"),
    metricOversold: document.querySelector("#metric-oversold"),
    metricStrongest: document.querySelector("#metric-strongest"),
    metricStrongestCaption: document.querySelector("#metric-strongest-caption"),
    assetTitle: document.querySelector("#asset-title"),
    assetTimeframe: document.querySelector("#asset-timeframe"),
    assetPlaceholder: document.querySelector("#asset-placeholder"),
    assetContent: document.querySelector("#asset-content"),
    assetStats: document.querySelector("#asset-stats"),
    rsiChart: document.querySelector("#rsi-chart"),
    priceChart: document.querySelector("#price-chart"),
    priceCaption: document.querySelector("#price-chart-caption"),
  };

  const number = new Intl.NumberFormat("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const compact = new Intl.NumberFormat("pt-BR", {
    notation: "compact",
    maximumFractionDigits: 2,
  });
  const currency = new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  });
  const signalLevelLabels = Object.freeze({
    NORMAL: "Normal",
    MODERATE: "Moderado",
    STRONG: "Forte",
    EXTREME: "Extremo",
  });

  async function request(path) {
    const response = await fetch(path, {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    const data = await response.json().catch(() => ({}));

    if (!response.ok || data.success === false) {
      throw new Error(data.error || "Não foi possível carregar os dados.");
    }

    return data;
  }

  function setConnection(ok, text) {
    elements.connection.classList.toggle("is-error", !ok);
    elements.connection.lastChild.textContent = ` ${text}`;
  }

  function escapeHTML(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function toNumber(value) {
    const numberValue = Number(value);
    return Number.isFinite(numberValue) ? numberValue : null;
  }

  function formatNumber(value) {
    const parsed = toNumber(value);
    return parsed === null ? "N/D" : number.format(parsed);
  }

  function formatSigned(value, suffix = "") {
    const parsed = toNumber(value);
    if (parsed === null) return "N/D";
    return `${parsed > 0 ? "+" : ""}${number.format(parsed)}${suffix}`;
  }

  function formatCurrency(value) {
    const parsed = toNumber(value);
    return parsed === null ? "N/D" : currency.format(parsed);
  }

  function levelClass(value) {
    return String(value || "").toLowerCase();
  }

  function signalLevelLabel(record) {
    if (record.signal_level_label) return record.signal_level_label;
    const level = String(record.signal_level || "NORMAL").toUpperCase();
    return signalLevelLabels[level] || "Não classificado";
  }

  function signalClass(record) {
    return record.signal_type === "OVERBOUGHT" ? "rsi-up" : "rsi-down";
  }

  async function loadTimeframes() {
    const data = await request("/api/v1/meta/timeframes");
    const supported = data.results || [];
    if (!supported.includes(state.intervalo)) state.intervalo = supported[0] || "1h";

    elements.timeframes.replaceChildren(
      ...supported.map((intervalo) => {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = intervalo;
        button.setAttribute("aria-pressed", String(intervalo === state.intervalo));
        button.addEventListener("click", () => {
          state.intervalo = intervalo;
          renderTimeframeButtons(supported);
          loadSignals();
          if (state.selectedSymbol) loadAsset(state.selectedSymbol);
        });
        return button;
      })
    );
  }

  function renderTimeframeButtons(supported) {
    [...elements.timeframes.children].forEach((button, index) => {
      button.setAttribute("aria-pressed", String(supported[index] === state.intervalo));
    });
  }

  async function loadSignals() {
    if (state.signalsLoading) return;
    state.signalsLoading = true;

    const params = new URLSearchParams({
      intervalo: state.intervalo,
      limite: "100",
    });
    if (state.signalType) params.set("tipo", state.signalType);
    if (state.signalLevel) params.set("nivel", state.signalLevel);

    elements.tableStatus.textContent = "Atualizando…";
    elements.refresh.disabled = true;

    try {
      const data = await request(`/api/v1/signals/current?${params}`);
      const records = data.results || [];
      state.records = records;
      renderSignals(records);
      updateMetrics(records);
      elements.tableStatus.textContent = `${records.length} sinais ativos`;
      setConnection(true, "Dados do mercado");
    } catch (error) {
      renderSignals([]);
      elements.tableStatus.textContent = "Dados indisponíveis";
      setConnection(false, "Falha ao carregar dados");
      elements.empty.hidden = false;
      elements.empty.querySelector("h3").textContent = "Não foi possível carregar o radar";
      elements.empty.querySelector("p").textContent = error.message;
    } finally {
      elements.refresh.disabled = false;
      state.signalsLoading = false;
    }
  }

  function renderSignals(records) {
    elements.body.replaceChildren();
    elements.empty.hidden = records.length > 0;

    records.forEach((record) => {
      const row = document.createElement("tr");
      const selected = record.symbol === state.selectedSymbol;
      row.classList.toggle("selected", selected);
      row.innerHTML = `
        <td>
          <div class="asset-cell">
            <span class="asset-icon">${escapeHTML(String(record.symbol || "?").slice(0, 2))}</span>
            <div><div>${escapeHTML(record.symbol)}</div><span class="subtle">#${escapeHTML(record.ranking ?? "—")}</span></div>
          </div>
        </td>
        <td class="${signalClass(record)}"><strong>${formatNumber(record.rsi)}</strong></td>
        <td class="${toNumber(record.rsi_difference) >= 0 ? "value-positive" : "value-negative"}">${formatSigned(record.rsi_difference)}</td>
        <td>${formatCurrency(record.current_price)}</td>
        <td class="${toNumber(record.change_24h) >= 0 ? "value-positive" : "value-negative"}">${formatSigned(record.change_24h, "%")}</td>
        <td><span class="level ${levelClass(record.signal_level)}">${escapeHTML(signalLevelLabel(record))}</span></td>
      `;
      row.addEventListener("click", () => selectRecord(record));
      elements.body.append(row);
    });
  }

  function updateMetrics(records) {
    const overbought = records.filter((item) => item.signal_type === "OVERBOUGHT");
    const oversold = records.filter((item) => item.signal_type === "OVERSOLD");
    const strongest = records[0];

    elements.metricTotal.textContent = String(records.length);
    elements.metricTotalCaption.textContent = `timeframe ${state.intervalo}`;
    elements.metricOverbought.textContent = String(overbought.length);
    elements.metricOversold.textContent = String(oversold.length);
    elements.metricStrongest.textContent = strongest ? strongest.symbol.replace("/USDT", "") : "—";
    elements.metricStrongestCaption.textContent = strongest
      ? `${signalLevelLabel(strongest)} · RSI ${formatNumber(strongest.rsi)}`
      : "aguardando sinais";
  }

  function selectRecord(record) {
    state.selectedRecord = record;
    state.selectedSymbol = record.symbol;
    renderSignals(state.records);
    loadAsset(record.symbol, record);
  }

  async function loadAsset(symbol, record = state.selectedRecord) {
    state.selectedSymbol = symbol;
    elements.assetTitle.textContent = symbol;
    elements.assetTimeframe.textContent = state.intervalo;
    elements.assetPlaceholder.hidden = true;
    elements.assetContent.hidden = false;
    elements.assetStats.innerHTML = '<div class="asset-stat"><span>Carregando</span><strong>…</strong></div>';
    elements.rsiChart.innerHTML = '<div class="chart-empty">Carregando histórico RSI…</div>';
    elements.priceChart.innerHTML = '<div class="chart-empty">Carregando candles…</div>';

    const safeSymbol = encodeURIComponent(symbol);
    const params = new URLSearchParams({
      intervalo: state.intervalo,
      limite: "180",
    });

    const [historyResult, candleResult] = await Promise.allSettled([
      request(`/api/v1/history/${safeSymbol}?${params}`),
      request(`/api/v1/market/${safeSymbol}/candles?${params}`),
    ]);

    const history = historyResult.status === "fulfilled" ? historyResult.value.results || [] : [];
    const candles = candleResult.status === "fulfilled" ? candleResult.value.results || [] : [];
    const latest = history.at(-1) || record;

    if (!latest) {
      elements.assetStats.innerHTML = '<div class="asset-stat"><span>Sem dados</span><strong>—</strong></div>';
      elements.rsiChart.innerHTML = '<div class="chart-empty">Ainda não há histórico para este par.</div>';
      elements.priceChart.innerHTML = '<div class="chart-empty">—</div>';
      return;
    }

    renderAssetStats(latest);
    renderLineChart(elements.rsiChart, history, "rsi", {
      color: "#61dfb5",
      min: 0,
      max: 100,
      thresholds: [30, 70],
    });
    renderLineChart(elements.priceChart, candles, "close", {
      color: "#85a8ff",
    });
    elements.priceCaption.textContent = candles.length ? `${candles.length} candles · Binance` : "dados indisponíveis";
  }

  function renderAssetStats(record) {
    const stats = [
      ["Preço atual", formatCurrency(record.current_price)],
      ["RSI", formatNumber(record.rsi)],
      ["Variação 24h", formatSigned(record.change_24h, "%")],
      ["Volume 24h", toNumber(record.volume_24h) === null ? "N/D" : `$${compact.format(record.volume_24h)}`],
      ["Diferença RSI", formatSigned(record.rsi_difference)],
      ["Ranking", record.ranking ? `#${record.ranking}` : "N/D"],
    ];
    elements.assetStats.innerHTML = stats.map(([label, value]) => `
      <div class="asset-stat"><span>${escapeHTML(label)}</span><strong>${escapeHTML(value)}</strong></div>
    `).join("");
  }

  function renderLineChart(target, records, key, options = {}) {
    const values = records
      .map((item) => toNumber(item[key]))
      .filter((value) => value !== null);

    if (values.length < 2) {
      target.innerHTML = '<div class="chart-empty">Histórico insuficiente para desenhar o gráfico.</div>';
      return;
    }

    const width = 440;
    const height = 164;
    const padding = { top: 12, right: 10, bottom: 17, left: 10 };
    const lower = options.min ?? Math.min(...values);
    const upper = options.max ?? Math.max(...values);
    const spread = upper - lower || Math.max(upper * 0.04, 1);
    const min = options.min ?? lower - spread * 0.14;
    const max = options.max ?? upper + spread * 0.14;
    const x = (index) => padding.left + (index / (values.length - 1)) * (width - padding.left - padding.right);
    const y = (value) => padding.top + (1 - (value - min) / (max - min)) * (height - padding.top - padding.bottom);
    const points = values.map((value, index) => `${x(index).toFixed(2)},${y(value).toFixed(2)}`).join(" ");

    const thresholds = (options.thresholds || []).map((threshold) => `
      <line x1="${padding.left}" x2="${width - padding.right}" y1="${y(threshold)}" y2="${y(threshold)}" stroke="#7389a5" stroke-opacity=".34" stroke-dasharray="4 4" />
      <text x="${width - padding.right}" y="${y(threshold) - 4}" fill="#7f94ae" text-anchor="end" font-size="9">${threshold}</text>
    `).join("");

    target.innerHTML = `
      <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Série temporal">
        <defs>
          <linearGradient id="area-${key}" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stop-color="${options.color}" stop-opacity=".27" />
            <stop offset="1" stop-color="${options.color}" stop-opacity="0" />
          </linearGradient>
        </defs>
        ${[.25, .5, .75].map((part) => `<line x1="${padding.left}" x2="${width - padding.right}" y1="${padding.top + part * (height - padding.top - padding.bottom)}" y2="${padding.top + part * (height - padding.top - padding.bottom)}" stroke="#8395ad" stroke-opacity=".11" />`).join("")}
        ${thresholds}
        <polygon points="${padding.left},${height - padding.bottom} ${points} ${width - padding.right},${height - padding.bottom}" fill="url(#area-${key})" />
        <polyline points="${points}" fill="none" stroke="${options.color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" />
        <circle cx="${x(values.length - 1)}" cy="${y(values.at(-1))}" r="3.2" fill="${options.color}" stroke="#091522" stroke-width="2" />
      </svg>
    `;
  }

  async function searchSymbols(query) {
    if (query.trim().length < 2) {
      elements.suggestions.hidden = true;
      return;
    }

    try {
      const data = await request(`/api/v1/symbols?q=${encodeURIComponent(query)}&limite=8`);
      const results = data.results || [];
      elements.suggestions.replaceChildren(
        ...results.map((symbol) => {
          const button = document.createElement("button");
          button.type = "button";
          button.textContent = symbol;
          button.addEventListener("click", () => {
            elements.search.value = symbol;
            elements.suggestions.hidden = true;
            loadAsset(symbol);
          });
          return button;
        })
      );
      elements.suggestions.hidden = results.length === 0;
    } catch {
      elements.suggestions.hidden = true;
    }
  }

  function bindEvents() {
    elements.type.addEventListener("change", () => {
      state.signalType = elements.type.value;
      loadSignals();
    });
    elements.level.addEventListener("change", () => {
      state.signalLevel = elements.level.value;
      loadSignals();
    });
    elements.refresh.addEventListener("click", () => loadSignals());
    elements.form.addEventListener("submit", (event) => {
      event.preventDefault();
      const symbol = elements.search.value.trim();
      if (symbol) loadAsset(symbol);
      elements.suggestions.hidden = true;
    });
    elements.search.addEventListener("input", () => {
      clearTimeout(state.suggestionsTimer);
      state.suggestionsTimer = setTimeout(
        () => searchSymbols(elements.search.value),
        220,
      );
    });
    document.addEventListener("click", (event) => {
      if (!elements.form.contains(event.target)) elements.suggestions.hidden = true;
    });
  }

  async function initialize() {
    bindEvents();
    try {
      await loadTimeframes();
      await loadSignals();
      const params = new URLSearchParams(window.location.search);
      const symbol = params.get("symbol");
      const intervalo = params.get("intervalo");
      if (intervalo && [...elements.timeframes.children].some((button) => button.textContent === intervalo)) {
        state.intervalo = intervalo;
        renderTimeframeButtons([...elements.timeframes.children].map((button) => button.textContent));
      }
      if (symbol) {
        elements.search.value = symbol;
        await loadAsset(symbol);
      }
    } catch (error) {
      setConnection(false, "Falha ao iniciar painel");
      elements.tableStatus.textContent = error.message;
    }
    window.setInterval(loadSignals, SIGNALS_REFRESH_MS);
  }

  initialize();
})();
