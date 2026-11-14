# -*- coding: utf-8 -*-
"""
Backtest das leituras (Fase 3) — roda as regras sobre todo o histórico e reporta,
para cada estado de cada tema: em quantos % dos últimos 365 dias ficou ativo e
quantas vezes ligou (oscilações).

Falha (exit != 0) se alguma leitura ficar ativa em mais de `max_freq_pct`% dos dias
ou oscilar mais que `max_oscilacoes` vezes no ano — isso é ruído de limiar, não leitura.
Use para calibrar os limiares em config/thresholds.json -> "sinais".

Uso:  py collector/backtest.py        (usa data/history.json)
Sem histórico suficiente, apenas avisa e sai com 0 (não quebra o CI sem dados).
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import signals as S  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _replay(points, cfg, default_min_run):
    estado, since, estados = S.debounce_band(
        points, cfg["enter_high"], cfg["exit_high"], cfg["enter_low"], cfg["exit_low"],
        cfg.get("min_run", default_min_run))
    linhas = []
    for alvo, nome in (("alto", "alto/alta"), ("baixo", "baixo/queda")):
        fa = S.freq_ano(estados, alvo)
        osc = S.num_oscilacoes(estados, alvo)
        linhas.append((nome, fa["pct"] if fa else None, osc))
    return estado, linhas


def run():
    history = _load(os.path.join(ROOT, "data", "history.json"), {})
    thr = _load(os.path.join(ROOT, "config", "thresholds.json"), {})
    sin = (thr.get("sinais") or {})
    bt = (thr.get("backtest") or {})
    max_freq = bt.get("max_freq_pct", 40)
    max_osc = bt.get("max_oscilacoes", 12)

    temas = []  # (rotulo, points, cfg, default_min_run)
    pp = sin.get("preco_percentil", {})
    for key, label in (("soja", "Soja R$/sc"), ("milho", "Milho R$/sc")):
        serie = history.get(key + "_brl") or []
        if len(serie) >= 40:
            temas.append((label, S.percentile_series(serie, pp.get("janela_dias", 365)), pp, 2))
    cb = sin.get("cambio", {})
    if len(history.get("usd") or []) >= 40:
        temas.append(("Dólar PTAX", S.change_series(history["usd"], cb.get("janela_var", 90), "pct"), cb, 2))
    jr = sin.get("juros", {})
    if len(history.get("selic") or []) >= 20:
        temas.append(("Selic", S.change_series(history["selic"], jr.get("janela_var", 90), "pp"), jr, 1))
    ch = sin.get("chuva", {})
    for key, label in (("chuva_go", "Chuva GO"), ("chuva_to", "Chuva TO")):
        serie = history.get(key + "_pct") or []
        if len(serie) >= 40:
            temas.append((label, [(p["date"], p["value"]) for p in serie], ch, 3))

    def checa_freq(cfg):
        return cfg.get("checar_frequencia", True)

    if not temas:
        print("[backtest] sem histórico suficiente ainda — nada a checar.")
        return 0

    print(f"{'tema':<14}{'estado':<14}{'% ano ativo':>12}{'oscilações':>12}   status")
    print("-" * 68)
    falhas = []
    for rotulo, points, cfg, dmr in temas:
        _, linhas = _replay(points, cfg, dmr)
        checar = checa_freq(cfg)
        for nome, pct, osc in linhas:
            status = "ok" if checar else "ok (frequência isenta)"
            if checar and pct is not None and pct > max_freq:
                status = f"FALHA (> {max_freq}% do ano ativo)"
                falhas.append(f"{rotulo}/{nome}: {pct}% > {max_freq}%")
            if osc > max_osc:
                status = f"FALHA (> {max_osc} oscilações)"
                falhas.append(f"{rotulo}/{nome}: {osc} oscilações > {max_osc}")
            pct_s = "—" if pct is None else f"{pct}%"
            print(f"{rotulo:<14}{nome:<14}{pct_s:>12}{osc:>12}   {status}")

    print("-" * 68)
    if falhas:
        print("RESULTADO: FALHA — limiares provavelmente ruidosos:")
        for f in falhas:
            print("  -", f)
        return 1
    print("RESULTADO: OK — nenhuma leitura excede os limites de ruído.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
