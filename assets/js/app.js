/* App principal do Painel Agro + Energia Solar */
(function () {
  "use strict";

  const state = { latest: null, history: null, thresholds: null, chart: null, currentKey: null };

  const PERIODS = [
    { id: "30", label: "30d", days: 30 },
    { id: "90", label: "90d", days: 90 },
    { id: "180", label: "6m", days: 180 },
    { id: "365", label: "1a", days: 365 },
    { id: "all", label: "Tudo", days: null },
  ];

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
      if (state.chart) renderChart(state.currentKey, getActivePeriod());
    });
  }
  function updateThemeIcon() {
    const cur = document.documentElement.getAttribute("data-theme");
    const isDark = cur === "dark" || (!cur && matchMedia("(prefers-color-scheme: dark)").matches);
    document.getElementById("themeToggle").textContent = isDark ? "☀️" : "🌙";
  }

  /* ---------- Carregamento de dados ---------- */
  async function loadJSON(path) {
    const r = await fetch(path + (path.includes("?") ? "&" : "?") + "t=" + Date.now());
    if (!r.ok) throw new Error(path + " -> HTTP " + r.status);
    return r.json();
  }

  async function boot() {
    initTheme();
    try {
      const [latest, thresholds] = await Promise.all([
        loadJSON("data/latest.json"),
        loadJSON("config/thresholds.json").catch(() => ({ regras: [], disclaimer: "" })),
      ]);
      state.latest = latest;
      state.thresholds = thresholds;
      renderAll();
    } catch (e) {
      document.getElementById("groups").innerHTML =
        '<p class="insight--empty">Não foi possível carregar os dados (' + e.message +
        '). Verifique se o coletor já gerou <code>data/latest.json</code>.</p>';
    }
    document.querySelectorAll("[data-close]").forEach((el) =>
      el.addEventListener("click", closeModal));
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });
  }

  /* ---------- Render ---------- */
  function renderAll() {
    const L = state.latest;
    const upd = Fmt.dateTimeBR(L.generated_at);
    document.getElementById("lastUpdate").textContent = "Atualizado: " + upd;
    document.getElementById("footerUpdate").textContent = "Última coleta dos dados: " + upd +
      " (horário de Brasília).";
    renderBanner();
    renderInsights();
    renderGroups();
    renderNews();
  }

  function renderBanner() {
    const L = state.latest;
    const stale = Object.values(L.indicators).filter((i) => i.stale).length;
    const el = document.getElementById("statusBanner");
    if (!stale && (!L.errors || !L.errors.length)) { el.hidden = true; return; }
    el.hidden = false;
    let msg = "";
    if (stale) msg += `⚠️ ${stale} indicador(es) exibindo dado em cache ou configurado (fonte temporariamente indisponível). `;
    msg += "Os demais estão atualizados.";
    el.textContent = msg;
  }

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

  function renderGroups() {
    const L = state.latest;
    const host = document.getElementById("groups");
    const inds = L.indicators;
    const html = (L.groups || []).map((g) => {
      const items = Object.keys(inds)
        .filter((k) => inds[k].group === g.id)
        .map((k) => cardHTML(k, inds[k]));
      if (!items.length) return "";
      return `<div class="group"><h3 class="group__label">${esc(g.label)}</h3>
        <div class="cards">${items.join("")}</div></div>`;
    }).join("");
    host.innerHTML = html;
    host.querySelectorAll(".card").forEach((c) =>
      c.addEventListener("click", () => openModal(c.getAttribute("data-key"))));
  }

  function valueHTML(ind) {
    if (ind.value == null) return '<span class="card__value">—</span>';
    const dec = Fmt.decimalsFor(ind);
    const n = Fmt.num(ind.value, dec);
    const unit = ind.unit || "";
    if (unit === "R$") return `<span class="card__value">R$ ${n}</span>`;
    if (unit.startsWith("US")) return `<span class="card__value">${n}<small> ${esc(unit)}</small></span>`;
    return `<span class="card__value">${n}<small> ${esc(unit)}</small></span>`;
  }

  function chgHTML(label, value, changeType) {
    const m = Fmt.changeMeta(value);
    const txt = value == null ? "—" : Fmt.signed(value, 2, Fmt.changeSuffix(changeType));
    return `<span class="chg chg--${m.cls}"><span class="chg__lbl">${label}</span> ` +
           `<span class="chg__val">${m.arrow} ${txt}</span></span>`;
  }

  function cardHTML(key, ind) {
    const badge = ind.manual ? '<span class="badge-manual" title="Valor configurado manualmente">manual</span>'
      : (ind.stale ? '<span class="badge-stale" title="Dado em cache; fonte indisponível">desatualizado</span>' : "");
    const c = ind.changes || {};
    return `<button class="card" data-key="${key}" type="button">
      <div class="card__top">
        <span class="card__label">${esc(ind.label)}</span>
      </div>
      ${valueHTML(ind)}
      <div class="card__changes">
        ${chgHTML("Dia", c.day, ind.change_type)}
        ${chgHTML("Mês", c.month, ind.change_type)}
        ${chgHTML("Ano", c.year, ind.change_type)}
      </div>
      <div class="card__src">${badge}<span>Fonte: ${esc(ind.source)} · ${Fmt.dateBR(ind.as_of)}</span></div>
    </button>`;
  }

  function renderNews() {
    const host = document.getElementById("news");
    const items = state.latest.news || [];
    if (!items.length) { host.innerHTML = '<p class="insight--empty">Sem notícias no momento.</p>'; return; }
    host.innerHTML = items.map((it) => {
      const meta = [it.source, it.date ? Fmt.dateTimeBR(it.date) : null].filter(Boolean).join(" · ");
      return `<a class="news-item" href="${encodeURI(it.link)}" target="_blank" rel="noopener noreferrer">
        <span class="news-item__cat">${esc(it.categoria || "")}</span>
        <div class="news-item__title">${esc(it.title)}</div>
        <div class="news-item__meta">${esc(meta)}</div>
      </a>`;
    }).join("");
  }

  /* ---------- Modal + gráfico ---------- */
  async function openModal(key) {
    state.currentKey = key;
    const ind = state.latest.indicators[key];
    document.getElementById("chartTitle").textContent = ind.label + (ind.unit ? "  (" + ind.unit + ")" : "");
    document.getElementById("chartSource").innerHTML =
      `Fonte: <a href="${esc(ind.source_url || "#")}" target="_blank" rel="noopener">${esc(ind.source)}</a>` +
      (ind.manual ? " · valor configurado manualmente" : "");
    const periodsHost = document.getElementById("chartPeriods");
    periodsHost.innerHTML = PERIODS.map((p, i) =>
      `<button class="period-btn ${i === 3 ? "active" : ""}" data-period="${p.id}">${p.label}</button>`).join("");
    periodsHost.querySelectorAll(".period-btn").forEach((b) =>
      b.addEventListener("click", () => {
        periodsHost.querySelectorAll(".period-btn").forEach((x) => x.classList.remove("active"));
        b.classList.add("active");
        renderChart(key, PERIODS.find((p) => p.id === b.getAttribute("data-period")));
      }));
    document.getElementById("chartModal").hidden = false;

    if (!state.history) {
      try { state.history = await loadJSON("data/history.json"); }
      catch (e) { state.history = {}; }
    }
    renderChart(key, PERIODS[3]); // 1 ano por padrão
  }

  function getActivePeriod() {
    const active = document.querySelector("#chartPeriods .period-btn.active");
    const id = active ? active.getAttribute("data-period") : "365";
    return PERIODS.find((p) => p.id === id) || PERIODS[3];
  }

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function renderChart(key, period) {
    const series = (state.history && state.history[key]) || [];
    let data = series.slice();
    if (period && period.days) {
      const cut = new Date(); cut.setDate(cut.getDate() - period.days);
      const cutIso = cut.toISOString().slice(0, 10);
      data = data.filter((p) => p.date >= cutIso);
    }
    const statsHost = document.getElementById("chartStats");
    if (!data.length) {
      if (state.chart) { state.chart.destroy(); state.chart = null; }
      statsHost.innerHTML = '<span>Sem histórico suficiente para este período. ' +
        'O histórico cresce a cada coleta.</span>';
      return;
    }
    const ind = state.latest.indicators[key];
    const dec = Fmt.decimalsFor(ind);
    const labels = data.map((p) => Fmt.dateBR(p.date));
    const values = data.map((p) => p.value);
    const max = Math.max.apply(null, values);
    const min = Math.min.apply(null, values);
    const accent = cssVar("--accent") || "#1f7a4d";
    const grid = cssVar("--border") || "#e2e7ee";
    const text = cssVar("--text-soft") || "#5b6775";

    if (state.chart) state.chart.destroy();
    const ctx = document.getElementById("chartCanvas").getContext("2d");
    state.chart = new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [{
          data: values, borderColor: accent, backgroundColor: accent + "22",
          borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.15, fill: true,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { intersect: false, mode: "index" },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (c) => Fmt.num(c.parsed.y, dec) + (ind.unit ? " " + ind.unit : ""),
            },
          },
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: text, maxTicksLimit: 8, autoSkip: true } },
          y: { grid: { color: grid }, ticks: { color: text, callback: (v) => Fmt.num(v, dec) } },
        },
      },
    });

    const first = data[0].date, last = data[data.length - 1].date;
    statsHost.innerHTML =
      `<span>Máxima: <b>${Fmt.num(max, dec)}</b></span>` +
      `<span>Mínima: <b>${Fmt.num(min, dec)}</b></span>` +
      `<span>Último: <b>${Fmt.num(values[values.length - 1], dec)}</b></span>` +
      `<span>Período: <b>${Fmt.dateBR(first)} → ${Fmt.dateBR(last)}</b> (${data.length} pontos)</span>`;
  }

  function closeModal() {
    document.getElementById("chartModal").hidden = true;
    if (state.chart) { state.chart.destroy(); state.chart = null; }
  }

  /* ---------- util ---------- */
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (m) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
