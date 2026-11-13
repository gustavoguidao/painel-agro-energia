/* App principal do Painel Agro + Energia Solar */
(function () {
  "use strict";

  const state = {
    latest: null, history: null, thresholds: null,
    chart: null, currentKey: null, chartUnit: "brl",
    unitPref: {}, tab: "visao", newsCat: "Todas",
  };

  const PERIODS = [
    { id: "30", label: "30d", days: 30 },
    { id: "90", label: "90d", days: 90 },
    { id: "180", label: "6m", days: 180 },
    { id: "365", label: "1a", days: 365 },
    { id: "all", label: "Tudo", days: null },
  ];

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  /* ---------- Tema ---------- */
  function initTheme() {
    let saved = null;
    try { saved = localStorage.getItem("theme"); } catch (e) {}
    if (saved) document.documentElement.setAttribute("data-theme", saved);
    updateThemeIcon();
    document.getElementById("themeToggle").addEventListener("click", function () {
      const cur = document.documentElement.getAttribute("data-theme");
      const isDark = cur === "dark" || (!cur && matchMedia("(prefers-color-scheme: dark)").matches);
      const next = isDark ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try { localStorage.setItem("theme", next); } catch (e) {}
      updateThemeIcon();
      if (state.latest) { renderGroups(); }
      if (state.chart) renderChart(state.currentKey, getActivePeriod());
    });
  }
  function updateThemeIcon() {
    const cur = document.documentElement.getAttribute("data-theme");
    const isDark = cur === "dark" || (!cur && matchMedia("(prefers-color-scheme: dark)").matches);
    document.getElementById("themeToggle").textContent = isDark ? "☀️" : "🌙";
  }

  /* ---------- Abas ---------- */
  function initTabs() {
    try { const t = localStorage.getItem("tab"); if (t) state.tab = t; } catch (e) {}
    document.querySelectorAll(".tab").forEach((btn) =>
      btn.addEventListener("click", () => setTab(btn.getAttribute("data-tab"))));
    setTab(state.tab);
  }
  function setTab(tab) {
    state.tab = tab;
    try { localStorage.setItem("tab", tab); } catch (e) {}
    document.querySelectorAll(".tab").forEach((b) =>
      b.setAttribute("aria-selected", b.getAttribute("data-tab") === tab ? "true" : "false"));
    ["recomendacoes", "visao", "noticias"].forEach((id) => {
      document.getElementById("panel-" + id).hidden = id !== tab;
    });
  }

  /* ---------- Carregamento ---------- */
  async function loadJSON(path) {
    const r = await fetch(path + (path.includes("?") ? "&" : "?") + "t=" + Date.now());
    if (!r.ok) throw new Error(path + " -> HTTP " + r.status);
    return r.json();
  }

  async function boot() {
    initTheme();
    initTabs();
    try {
      const [latest, history, thresholds] = await Promise.all([
        loadJSON("data/latest.json"),
        loadJSON("data/history.json").catch(() => ({})),
        loadJSON("config/thresholds.json").catch(() => ({ regras: [], disclaimer: "" })),
      ]);
      state.latest = latest;
      state.history = history;
      state.thresholds = thresholds;
      renderAll();
    } catch (e) {
      document.getElementById("groups").innerHTML =
        '<p class="insight--empty">Não foi possível carregar os dados (' + e.message +
        '). Verifique se o coletor já gerou <code>data/latest.json</code>.</p>';
    }
    document.querySelectorAll("[data-close]").forEach((el) => el.addEventListener("click", closeModal));
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });
    bindCalc();
  }

  /* ---------- Render geral ---------- */
  function renderAll() {
    const L = state.latest;
    const upd = Fmt.dateTimeBR(L.generated_at);
    document.getElementById("lastUpdate").textContent = "Atualizado: " + upd;
    document.getElementById("footerUpdate").textContent = "Última coleta dos dados: " + upd + " (horário de Brasília).";
    renderBanner();
    renderInsights();
    renderGroups();
    renderNews();
    computeCalc();
  }

  function renderBanner() {
    const L = state.latest;
    const stale = Object.values(L.indicators).filter((i) => i.stale).length;
    const el = document.getElementById("statusBanner");
    if (!stale) { el.hidden = true; return; }
    el.hidden = false;
    el.textContent = `⚠️ ${stale} indicador(es) exibindo dado em cache ou configurado (fonte temporariamente indisponível). Os demais estão atualizados.`;
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (m) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
  }

  /* ---------- Recomendações ---------- */
  function renderInsights() {
    const host = document.getElementById("insights");
    const fired = Recomendacoes.evaluate(state.latest.indicators, state.thresholds);
    document.getElementById("insightsDisclaimer").textContent =
      (state.thresholds && state.thresholds.disclaimer) || "";
    if (!fired.length) {
      host.innerHTML = '<p class="insight--empty">Nenhuma recomendação disparada com os dados atuais. ' +
        'Os limiares podem ser ajustados em <code>config/thresholds.json</code>.</p>';
      return;
    }
    host.innerHTML = fired.map(({ regra, triggers }) => {
      const sev = regra.severidade || "neutro";
      return `<article class="insight insight--${sev}">
        <h3 class="insight__title">${esc(regra.titulo)}</h3>
        <p class="insight__msg">${esc(regra.mensagem)}</p>
        <div class="insight__trigger">Disparado por: ${triggers.join(" &nbsp;·&nbsp; ")}</div>
      </article>`;
    }).join("");
  }

  /* ---------- Sparkline ---------- */
  function sparkSVG(series) {
    const pts = (series || []).slice(-30);
    if (pts.length < 2) return '<div class="spark"></div>';
    const vals = pts.map((p) => p.value);
    const min = Math.min.apply(null, vals), max = Math.max.apply(null, vals);
    const range = (max - min) || 1;
    const n = pts.length;
    const coords = vals.map((v, i) => {
      const x = (i / (n - 1)) * 100;
      const y = 32 - ((v - min) / range) * 30;
      return x.toFixed(2) + "," + y.toFixed(2);
    });
    const up = vals[vals.length - 1] >= vals[0];
    const color = up ? cssVar("--up") : cssVar("--down");
    const d = "M" + coords.join(" L");
    return `<svg class="spark" viewBox="0 0 100 34" preserveAspectRatio="none" aria-hidden="true">
      <path d="${d} L100,34 L0,34 Z" fill="${color}" opacity="0.10"></path>
      <path d="${d}" fill="none" stroke="${color}" stroke-width="2" vector-effect="non-scaling-stroke" stroke-linejoin="round" stroke-linecap="round"></path>
    </svg>`;
  }

  /* ---------- View por card (resolve unidade preferida) ---------- */
  function cardView(key, ind) {
    const pref = state.unitPref[key] || "brl";
    if (ind.alt_brl && pref === "orig") {
      return {
        value: ind.value, unit: ind.unit, decimals: Fmt.decimalsFor(ind),
        changes: ind.changes, series: (state.history || {})[key],
        alt: "R$ " + Fmt.num(ind.alt_brl.value, 2) + "/sc",
      };
    }
    if (ind.alt_brl) {
      return {
        value: ind.alt_brl.value, unit: "R$/sc", decimals: 2,
        changes: ind.alt_brl.changes, series: (state.history || {})[ind.alt_brl.history_key],
        alt: Fmt.num(ind.value, Fmt.decimalsFor(ind)) + " " + ind.unit + " · futuro",
      };
    }
    return {
      value: ind.value, unit: ind.unit, decimals: Fmt.decimalsFor(ind),
      changes: ind.changes, series: (state.history || {})[key], alt: null,
    };
  }

  function valueHTML(value, unit, decimals) {
    if (value == null) return '<span class="card__value">—</span>';
    const n = Fmt.num(value, decimals);
    if (unit === "R$") return `<span class="card__value">R$ ${n}</span>`;
    if (unit === "R$/sc") return `<span class="card__value">R$ ${n}<small> /sc</small></span>`;
    return `<span class="card__value">${n}<small> ${esc(unit)}</small></span>`;
  }

  function chgHTML(label, value, changeType) {
    const m = Fmt.changeMeta(value);
    const txt = value == null ? "—" : Fmt.signed(value, 2, Fmt.changeSuffix(changeType));
    return `<span class="chg chg--${m.cls}">${label} <span class="chg__val">${m.arrow} ${txt}</span></span>`;
  }

  function cardHTML(key, ind) {
    const v = cardView(key, ind);
    const ct = ind.alt_brl && (state.unitPref[key] || "brl") === "brl" ? "pct" : ind.change_type;
    const badge = ind.manual ? '<span class="badge-manual" title="Valor configurado manualmente">manual</span>'
      : (ind.stale ? '<span class="badge-stale" title="Dado em cache; fonte indisponível">desatualizado</span>' : "");
    const toggle = ind.alt_brl ? (() => {
      const pref = state.unitPref[key] || "brl";
      return `<span class="unit-toggle" data-key="${key}">
        <button data-unit="brl" class="${pref === "brl" ? "active" : ""}">R$/sc</button>
        <button data-unit="orig" class="${pref === "orig" ? "active" : ""}">US¢</button>
      </span>`;
    })() : "";
    const alt = v.alt ? `<div class="card__alt">${esc(v.alt)}</div>` : "";
    const c = v.changes || {};
    return `<div class="card" data-key="${key}" role="button" tabindex="0">
      <div class="card__top">
        <span class="card__label">${esc(ind.label)}</span>
        ${toggle}
      </div>
      ${valueHTML(v.value, v.unit, v.decimals)}
      ${alt}
      ${sparkSVG(v.series)}
      <div class="card__changes">
        ${chgHTML("Dia", c.day, ct)}
        ${chgHTML("Mês", c.month, ct)}
        ${chgHTML("Ano", c.year, ct)}
      </div>
      <div class="card__src">${badge}<span>Fonte: ${esc(ind.source)} · ${Fmt.dateBR(ind.as_of)}</span></div>
    </div>`;
  }

  function renderGroups() {
    const L = state.latest;
    const host = document.getElementById("groups");
    const inds = L.indicators;
    host.innerHTML = (L.groups || []).map((g) => {
      const items = Object.keys(inds).filter((k) => inds[k].group === g.id).map((k) => cardHTML(k, inds[k]));
      if (!items.length) return "";
      return `<div class="group"><h3 class="group__label">${esc(g.label)}</h3><div class="cards">${items.join("")}</div></div>`;
    }).join("");

    // toggles de unidade (não abrem o gráfico)
    host.querySelectorAll(".unit-toggle button").forEach((b) => {
      b.addEventListener("click", (e) => {
        e.stopPropagation();
        const key = b.parentElement.getAttribute("data-key");
        state.unitPref[key] = b.getAttribute("data-unit");
        renderGroups();
      });
    });
    // abrir gráfico
    host.querySelectorAll(".card").forEach((c) => {
      const open = () => openModal(c.getAttribute("data-key"));
      c.addEventListener("click", open);
      c.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
    });
  }

  /* ---------- Notícias ---------- */
  function renderNews() {
    const items = state.latest.news || [];
    const cats = ["Todas"].concat(Array.from(new Set(items.map((i) => i.categoria).filter(Boolean))));
    const fhost = document.getElementById("newsFilter");
    fhost.innerHTML = cats.map((c) =>
      `<button data-cat="${esc(c)}" class="${state.newsCat === c ? "active" : ""}">${esc(c)}</button>`).join("");
    fhost.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
      state.newsCat = b.getAttribute("data-cat"); renderNews();
    }));

    const host = document.getElementById("news");
    const list = state.newsCat === "Todas" ? items : items.filter((i) => i.categoria === state.newsCat);
    if (!list.length) { host.innerHTML = '<p class="insight--empty">Sem notícias nesta categoria.</p>'; return; }
    host.innerHTML = list.map((it) => {
      const meta = [it.source, it.date ? Fmt.dateTimeBR(it.date) : null].filter(Boolean).join(" · ");
      return `<a class="news-item" href="${encodeURI(it.link)}" target="_blank" rel="noopener noreferrer">
        <span class="news-item__cat">${esc(it.categoria || "")}</span>
        <div class="news-item__title">${esc(it.title)}</div>
        <div class="news-item__meta">${esc(meta)}</div>
      </a>`;
    }).join("");
  }

  /* ---------- Calculadora de payback solar ---------- */
  function bindCalc() {
    ["calcConsumo", "calcTarifa", "calcCusto", "calcCompensacao"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.addEventListener("input", computeCalc);
    });
  }
  function computeCalc() {
    const num = (id) => parseFloat((document.getElementById(id) || {}).value);
    const consumo = num("calcConsumo"), tarifa = num("calcTarifa"),
          custo = num("calcCusto"), comp = num("calcCompensacao");
    const host = document.getElementById("calcResults");
    if (!host) return;
    const brl = (v) => "R$ " + Fmt.num(v, 2);
    if (![consumo, tarifa, custo, comp].every((x) => !isNaN(x))) {
      host.innerHTML = '<div class="result"><div class="result__label">Preencha os campos</div></div>';
      return;
    }
    const economiaMes = consumo * tarifa * (comp / 100);
    const economiaAno = economiaMes * 12;
    const payback = economiaAno > 0 ? custo / economiaAno : null;
    const economia25 = economiaAno * 25 - custo;
    host.innerHTML =
      `<div class="result"><div class="result__label">Economia mensal</div><div class="result__value">${brl(economiaMes)}</div></div>` +
      `<div class="result"><div class="result__label">Economia anual</div><div class="result__value">${brl(economiaAno)}</div></div>` +
      `<div class="result result--hero"><div class="result__label">Payback estimado</div><div class="result__value">${payback == null ? "—" : Fmt.num(payback, 1) + " anos"}</div></div>` +
      `<div class="result"><div class="result__label">Economia em 25 anos</div><div class="result__value">${brl(economia25)}</div></div>`;
  }

  /* ---------- Modal + gráfico ---------- */
  function openModal(key) {
    state.currentKey = key;
    const ind = state.latest.indicators[key];
    state.chartUnit = ind.alt_brl ? ((state.unitPref[key] || "brl") === "orig" ? "orig" : "brl") : "orig";

    document.getElementById("chartSource").innerHTML =
      `Fonte: <a href="${esc(ind.source_url || "#")}" target="_blank" rel="noopener">${esc(ind.source)}</a>` +
      (ind.manual ? " · valor configurado manualmente" : "") + (ind.note ? " · " + esc(ind.note) : "");

    const periodsHost = document.getElementById("chartPeriods");
    periodsHost.innerHTML = PERIODS.map((p, i) =>
      `<button class="period-btn ${i === 3 ? "active" : ""}" data-period="${p.id}">${p.label}</button>`).join("");
    periodsHost.querySelectorAll(".period-btn").forEach((b) => b.addEventListener("click", () => {
      periodsHost.querySelectorAll(".period-btn").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      renderChart(key, PERIODS.find((p) => p.id === b.getAttribute("data-period")));
    }));

    const unitsHost = document.getElementById("chartUnits");
    if (ind.alt_brl) {
      unitsHost.innerHTML =
        `<button class="unit-btn ${state.chartUnit === "brl" ? "active" : ""}" data-u="brl">R$/saca</button>` +
        `<button class="unit-btn ${state.chartUnit === "orig" ? "active" : ""}" data-u="orig">US¢ (futuro)</button>`;
      unitsHost.querySelectorAll(".unit-btn").forEach((b) => b.addEventListener("click", () => {
        state.chartUnit = b.getAttribute("data-u");
        unitsHost.querySelectorAll(".unit-btn").forEach((x) => x.classList.remove("active"));
        b.classList.add("active");
        renderChart(key, getActivePeriod());
      }));
    } else { unitsHost.innerHTML = ""; }

    document.getElementById("chartModal").hidden = false;
    renderChart(key, PERIODS[3]);
  }

  function getActivePeriod() {
    const active = document.querySelector("#chartPeriods .period-btn.active");
    const id = active ? active.getAttribute("data-period") : "365";
    return PERIODS.find((p) => p.id === id) || PERIODS[3];
  }

  function renderChart(key, period) {
    const ind = state.latest.indicators[key];
    const useBrl = ind.alt_brl && state.chartUnit === "brl";
    const hk = useBrl ? ind.alt_brl.history_key : key;
    const unit = useBrl ? "R$/saca" : ind.unit;
    const dec = useBrl ? 2 : Fmt.decimalsFor(ind);
    document.getElementById("chartTitle").textContent = ind.label + (unit ? "  (" + unit + ")" : "");

    const series = (state.history && state.history[hk]) || [];
    let data = series.slice();
    if (period && period.days) {
      const cut = new Date(); cut.setDate(cut.getDate() - period.days);
      const cutIso = cut.toISOString().slice(0, 10);
      data = data.filter((p) => p.date >= cutIso);
    }
    const statsHost = document.getElementById("chartStats");
    if (!data.length) {
      if (state.chart) { state.chart.destroy(); state.chart = null; }
      statsHost.innerHTML = '<span>Sem histórico suficiente para este período. O histórico cresce a cada coleta.</span>';
      return;
    }
    const labels = data.map((p) => Fmt.dateBR(p.date));
    const values = data.map((p) => p.value);
    const max = Math.max.apply(null, values), min = Math.min.apply(null, values);
    const accent = cssVar("--accent") || "#0f7a43";
    const grid = cssVar("--grid"), text = cssVar("--muted");

    if (state.chart) state.chart.destroy();
    const ctx = document.getElementById("chartCanvas").getContext("2d");
    state.chart = new Chart(ctx, {
      type: "line",
      data: { labels, datasets: [{ data: values, borderColor: accent, backgroundColor: accent + "20", borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.15, fill: true }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { intersect: false, mode: "index" },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (c) => Fmt.num(c.parsed.y, dec) + (unit ? " " + unit : "") } },
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: text, maxTicksLimit: 8, autoSkip: true } },
          y: { grid: { color: grid }, ticks: { color: text, callback: (v) => Fmt.num(v, dec) } },
        },
      },
    });

    statsHost.innerHTML =
      `<span>Máxima: <b>${Fmt.num(max, dec)}</b></span>` +
      `<span>Mínima: <b>${Fmt.num(min, dec)}</b></span>` +
      `<span>Último: <b>${Fmt.num(values[values.length - 1], dec)}</b></span>` +
      `<span>Período: <b>${Fmt.dateBR(data[0].date)} → ${Fmt.dateBR(data[data.length - 1].date)}</b> (${data.length} pontos)</span>`;
  }

  function closeModal() {
    document.getElementById("chartModal").hidden = true;
    if (state.chart) { state.chart.destroy(); state.chart = null; }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
