/* Formatação pt-BR (números, datas, variações) */
(function (global) {
  "use strict";

  const DECIMALS = { cambio: 2, macro: 2, energia: 2, commodities: 2 };

  function decimalsFor(ind) {
    return DECIMALS[ind.group] != null ? DECIMALS[ind.group] : 2;
  }

  function num(value, decimals) {
    if (value == null || isNaN(value)) return "—";
    return new Intl.NumberFormat("pt-BR", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    }).format(value);
  }

  function signed(value, decimals, suffix) {
    if (value == null || isNaN(value)) return "—";
    const s = new Intl.NumberFormat("pt-BR", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
      signDisplay: "exceptZero",
    }).format(value);
    return s + (suffix || "");
  }

  function changeMeta(value) {
    if (value == null || isNaN(value)) return { cls: "flat", arrow: "–" };
    if (value > 0) return { cls: "up", arrow: "▲" };
    if (value < 0) return { cls: "down", arrow: "▼" };
    return { cls: "flat", arrow: "–" };
  }

  // Sufixo da variação conforme o tipo do indicador
  function changeSuffix(changeType) {
    return changeType === "pp" ? " p.p." : "%";
  }

  function dateBR(iso) {
    if (!iso) return "—";
    const d = iso.length <= 10 ? new Date(iso + "T00:00:00") : new Date(iso);
    if (isNaN(d)) return iso;
    return new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric" }).format(d);
  }

  function dateTimeBR(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    return new Intl.DateTimeFormat("pt-BR", {
      day: "2-digit", month: "2-digit", year: "numeric",
      hour: "2-digit", minute: "2-digit", timeZone: "America/Sao_Paulo",
    }).format(d);
  }

  global.Fmt = { decimalsFor, num, signed, changeMeta, changeSuffix, dateBR, dateTimeBR };
})(window);
