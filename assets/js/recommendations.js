/* Motor de regras das recomendações (transparente e configurável).
   Lê config/thresholds.json e os indicadores atuais; devolve as regras disparadas,
   mostrando SEMPRE o indicador e o limiar que as acionaram. */
(function (global) {
  "use strict";

  const OPS = {
    "<": (a, b) => a < b,
    "<=": (a, b) => a <= b,
    ">": (a, b) => a > b,
    ">=": (a, b) => a >= b,
    "==": (a, b) => a === b,
    "!=": (a, b) => a !== b,
  };

  const CAMPO_LABEL = {
    "value": "valor atual",
    "changes.day": "variação no dia",
    "changes.month": "variação no mês",
    "changes.year": "variação no ano",
  };

  function resolve(indicator, campo) {
    if (!indicator) return null;
    if (campo === "value") return indicator.value;
    if (campo.startsWith("changes.")) {
      const k = campo.split(".")[1];
      return indicator.changes ? indicator.changes[k] : null;
    }
    return null;
  }

  function fmtCond(indicator, cond) {
    const val = resolve(indicator, cond.campo);
    const isChange = cond.campo.startsWith("changes.");
    const suffix = isChange ? Fmt.changeSuffix(indicator.change_type) : (indicator.unit ? " " + indicator.unit : "");
    const valStr = val == null ? "—" : Fmt.num(val, isChange ? 2 : Fmt.decimalsFor(indicator)) + suffix;
    const limStr = Fmt.num(cond.limiar, 2);
    return `<b>${indicator.label}</b> (${CAMPO_LABEL[cond.campo] || cond.campo}) = ${valStr} ` +
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
        const ind = indicators[cond.indicador];
        const val = resolve(ind, cond.campo);
        const op = OPS[cond.operador];
        const ok = ind && val != null && op && op(val, cond.limiar);
        if (!ok) { allOk = false; break; }
        triggers.push(fmtCond(ind, cond));
      }
      if (allOk) fired.push({ regra, triggers });
    }
    return fired;
  }

  global.Recomendacoes = { evaluate };
})(window);
