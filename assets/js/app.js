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

  // Idade relativa da coleta: "há 8 h"; ambar acima de 8 h, vermelho acima de 24 h.
  function relAge(iso) {
    const d = new Date(iso);
    if (isNaN(d)) return { text: "—", cls: "" };
    const h = (Date.now() - d.getTime()) / 3.6e6;
    let text;
    if (h < 1) text = "há " + Math.max(1, Math.round(h * 60)) + " min";
    else if (h < 48) text = "há " + Math.round(h) + " h";
    else text = "há " + Math.round(h / 24) + " dias";
    return { text: text, cls: h > 24 ? "age-red" : (h > 8 ? "age-amber" : "") };
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
    const sun = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
    const moon = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.8A8.5 8.5 0 1 1 11.2 3a6.5 6.5 0 0 0 9.8 9.8z"/></svg>';
    document.getElementById("themeToggle").innerHTML = isDark ? sun : moon;
  }

  /* ---------- Abas ---------- */
  function initTabs() {
    try { const t = localStorage.getItem("tab"); if (t) state.tab = t; } catch (e) {}
    const tabs = Array.from(document.querySelectorAll(".tab"));
    tabs.forEach((btn, i) => {
      btn.addEventListener("click", () => setTab(btn.getAttribute("data-tab")));
      btn.addEventListener("keydown", (e) => {
        let j = null;
        if (e.key === "ArrowRight") j = (i + 1) % tabs.length;
        else if (e.key === "ArrowLeft") j = (i - 1 + tabs.length) % tabs.length;
        else if (e.key === "Home") j = 0;
        else if (e.key === "End") j = tabs.length - 1;
        if (j === null) return;
        e.preventDefault();
        setTab(tabs[j].getAttribute("data-tab"));
        tabs[j].focus();
      });
    });
    setTab(state.tab);
  }
  function setTab(tab) {
    state.tab = tab;
    try { localStorage.setItem("tab", tab); } catch (e) {}
    document.querySelectorAll(".tab").forEach((b) => {
      const active = b.getAttribute("data-tab") === tab;
      b.setAttribute("aria-selected", active ? "true" : "false");
      b.tabIndex = active ? 0 : -1;
    });
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
    const age = relAge(L.generated_at);
    const lu = document.getElementById("lastUpdate");
    lu.textContent = "coletado " + age.text;
    lu.className = "last-update " + age.cls;
    lu.title = "Última coleta: " + Fmt.dateTimeBR(L.generated_at) + " (horário de Brasília)";
    document.getElementById("footerUpdate").textContent =
      "Última coleta dos dados: " + Fmt.dateTimeBR(L.generated_at) + " (horário de Brasília).";
    renderBanner();
    renderInsights();
    renderGroups();
    renderNews();
    computeCalc();
  }

  function renderBanner() {
    const L = state.latest;
    const stale = Object.values(L.indicators).filter((i) => i.stale && i.value != null);
    const el = document.getElementById("statusBanner");
    if (!stale.length) { el.hidden = true; return; }
    el.hidden = false;
    const names = stale.map((i) => esc(i.label) + (i.as_of ? " (de " + Fmt.dateBR(i.as_of) + ")" : "")).join("; ");
    el.innerHTML = "⚠️ Exibindo em cache: " + names + ". Os demais estão atualizados.";
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
    const disc = (state.thresholds && state.thresholds.disclaimer) || "";
    host.innerHTML = fired.map(({ regra, triggers }) => {
      const sev = regra.severidade || "neutro";
      const sevLabel = sev === "positivo" ? "Positivo" : sev === "alerta" ? "Alerta" : "Info";
      return `<article class="insight insight--${sev}">
        <div class="insight__sev">${sevLabel}</div>
        <h3 class="insight__title">${esc(regra.titulo)}</h3>
        <p class="insight__msg">${esc(regra.mensagem)}</p>
        <div class="insight__trigger">Disparado por: ${triggers.join(" &nbsp;·&nbsp; ")}</div>
        <p class="insight__note">${esc(disc)}</p>
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
        alt: "R$ " + Fmt.num(ind.alt_brl.value, 2) + "/sc em R$/saca",
      };
    }
    if (ind.alt_brl) {
      return {
        value: ind.alt_brl.value, unit: "R$/sc", decimals: 2,
        changes: ind.alt_brl.changes, series: (state.history || {})[ind.alt_brl.history_key],
        alt: Fmt.num(ind.value, Fmt.decimalsFor(ind)) + " " + ind.unit,
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

  function changeRows(freq, c, ct) {
    c = c || {};
    if (freq === "monthly") return chgHTML("Mês", c.month, ct) + chgHTML("Ano", c.year, ct);
    if (freq === "weekly") return chgHTML("Semana", c.week, ct) + chgHTML("Mês", c.month, ct) + chgHTML("Ano", c.year, ct);
    return chgHTML("Dia", c.day, ct) + chgHTML("Mês", c.month, ct) + chgHTML("Ano", c.year, ct);
  }

  function cardHTML(key, ind) {
    // Estado honesto quando nao ha dado (ex.: boi sem fonte automatica): nao inventa numero.
    if (ind.value == null) {
      return `<div class="card card--empty">
        <div class="card__top"><span class="card__label">${esc(ind.label)}</span></div>
        <div class="card__nodata">sem dado</div>
        ${ind.note ? `<div class="card__note">${esc(ind.note)}</div>` : ""}
        <div class="card__src"><span>Fonte: ${esc(ind.source)}</span></div>
      </div>`;
    }
    const v = cardView(key, ind);
    const pref = state.unitPref[key] || "brl";
    const isCommodity = !!ind.alt_brl;
    const ct = isCommodity && pref === "brl" ? "pct" : ind.change_type;
    const badge = ind.manual ? '<span class="badge-manual" title="Valor configurado manualmente">manual</span>'
      : (ind.stale ? '<span class="badge-stale" title="Dado em cache; fonte indisponível">desatualizado</span>' : "");
    const toggle = isCommodity ? `<span class="unit-toggle" data-key="${key}">
        <button type="button" data-unit="brl" class="${pref === "brl" ? "active" : ""}">R$/sc</button>
        <button type="button" data-unit="orig" class="${pref === "orig" ? "active" : ""}">US¢</button>
      </span>` : "";
    const alt = v.alt ? `<div class="card__alt">${esc(v.alt)}</div>` : "";
    let notes = "";
    if (isCommodity && pref === "brl") {
      notes += `<div class="card__note">Paridade Chicago (sem prêmio, frete e base)`
        + (ind.alt_brl.note ? " · " + esc(ind.alt_brl.note) : "") + `</div>`;
    }
    if (ind.acum_12m != null) notes += `<div class="card__note">Acum. 12m: <b>${Fmt.num(ind.acum_12m, 2)}%</b></div>`;
    return `<div class="card" data-key="${key}" role="button" tabindex="0">
      <div class="card__top">
        <span class="card__label">${esc(ind.label)}</span>
        ${toggle}
      </div>
      ${valueHTML(v.value, v.unit, v.decimals)}
      ${alt}${notes}
      ${sparkSVG(v.series)}
      <div class="card__changes">${changeRows(ind.frequency, v.changes, ct)}</div>
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
    // abrir gráfico (apenas cards com dado)
    host.querySelectorAll(".card[data-key]").forEach((c) => {
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
    // NAO exibimos "economia em 25 anos" sem desconto (VPL/TIR descontado pela Selic virao na Fase 4).
    host.innerHTML =
      `<div class="result"><div class="result__label">Economia mensal</div><div class="result__value">${brl(economiaMes)}</div></div>` +
      `<div class="result"><div class="result__label">Economia anual</div><div class="result__value">${brl(economiaAno)}</div></div>` +
      `<div class="result result--hero"><div class="result__label">Payback simples</div><div class="result__value">${payback == null ? "—" : Fmt.num(payback, 1) + " anos"}</div></div>`;
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
