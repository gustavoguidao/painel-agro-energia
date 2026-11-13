/* Motor de regras das leituras de mercado (transparente e configurável).
   - Commodities (com alt_brl) são avaliadas em R$/saca, não em US¢.
   - Uma regra NÃO dispara se algum indicador usado estiver sem dado ou com a fonte vencida.
   - Cada condição mostra o indicador, a série/unidade e o limiar que a acionou. */
(function (global) {
  "use strict";

  const OPS = {
    "<": (a, b) => a < b, "<=": (a, b) => a <= b,
    ">": (a, b) => a > b, ">=": (a, b) => a >= b,
    "==": (a, b) => a === b, "!=": (a, b) => a !== b,
  };

  const CAMPO_LABEL = {
    "value": "valor atual",
    "acum_12m": "acumulado 12m",
    "changes.day": "variação no dia",
    "changes.week": "variação na semana",
    "changes.month": "variação no mês",
    "changes.quarter": "variação no trimestre",
    "changes.year": "variação no ano",
  };

  // Visão sobre a qual a regra é avaliada: commodities usam R$/saca (alt_brl).
  function priceView(ind) {
    if (!ind) return null;
    if (ind.alt_brl) {
      return {
        label: ind.label, value: ind.alt_brl.value, changes: ind.alt_brl.changes,
        unit: ind.alt_brl.unit, acum_12m: ind.acum_12m, change_type: "pct",
        stale: !!(ind.alt_brl.stale || ind.fonte_velha),
      };
    }
    return {
      label: ind.label, value: ind.value, changes: ind.changes,
      unit: ind.unit, acum_12m: ind.acum_12m, change_type: ind.change_type,
      stale: !!ind.fonte_velha,
    };
  }

  function resolve(view, campo) {
    if (!view) return null;
    if (campo === "value") return view.value;
    if (campo === "acum_12m") return view.acum_12m == null ? null : view.acum_12m;
    if (campo.indexOf("changes.") === 0) {
      const k = campo.split(".")[1];
      return view.changes ? view.changes[k] : null;
    }
    return null;
  }

  function fmtCond(view, cond) {
    const campo = cond.campo;
    const val = resolve(view, campo);
    const isChange = campo.indexOf("changes.") === 0;
    let suffix;
    if (campo === "acum_12m") suffix = "%";
    else if (isChange) suffix = Fmt.changeSuffix(view.change_type);
    else suffix = view.unit ? " " + view.unit : "";
    const valStr = val == null ? "—" : Fmt.num(val, 2) + suffix;
    const limStr = Fmt.num(cond.limiar, 2);
    return `<b>${view.label}</b> (${CAMPO_LABEL[campo] || campo}) = ${valStr} ` +
           `<span>— limiar: ${cond.operador} ${limStr}</span>`;
  }

  function evaluate(indicators, config) {
    const fired = [];
    const regras = (config && config.regras) || [];
    for (const regra of regras) {
      const conds = regra.quando || [];
      let allOk = conds.length > 0;
      const triggers = [];
      for (const cond of conds) {
        const view = priceView(indicators[cond.indicador]);
        if (!view || view.value == null) { allOk = false; break; }   // sem dado
        if (view.stale) { allOk = false; break; }                     // insumo vencido
        const val = resolve(view, cond.campo);
        const op = OPS[cond.operador];
        if (val == null || !op || !op(val, cond.limiar)) { allOk = false; break; }
        triggers.push(fmtCond(view, cond));
      }
      if (allOk) fired.push({ regra, triggers });
    }
    return fired;
  }

  global.Recomendacoes = { evaluate };
})(window);
