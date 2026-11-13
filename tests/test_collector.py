# -*- coding: utf-8 -*-
"""
Testes do coletor (Fase 1). Rodam com pytest OU direto:
    py -m pytest tests/ -q
    py tests/test_collector.py
Sem dependencias alem da stdlib + o proprio collect.py.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "collector"))

import collect  # noqa: E402


# ----- Conversao R$/saca -----
def test_to_brl_saca_bushel():
    # soja: 1200 US¢/bushel, dolar 5,00, 27,2155 kg/bushel
    v = collect.to_brl_saca(1200.0, 5.0, collect.SACA_CONV["soja"])
    assert round(v, 2) == 132.28


def test_to_brl_saca_lb():
    # cafe: 300 US¢/lb, dolar 5,00 -> (3/0,453592)*60*5
    v = collect.to_brl_saca(300.0, 5.0, collect.SACA_CONV["cafe"])
    assert round(v, 2) == 1984.16


# ----- Variacoes por frequencia -----
def test_changes_monthly_sem_dia():
    serie = [
        {"date": "2026-08-01", "value": 0.20},
        {"date": "2026-09-01", "value": 0.30},
        {"date": "2026-10-01", "value": 0.14},
    ]
    c = collect.compute_changes(serie, "pp", "monthly")
    assert c["day"] is None                 # serie mensal nao tem "dia"
    assert c["month"] == round(0.14 - 0.30, 4)  # compara com o mes anterior (nao 30 dias corridos)


def test_changes_daily_tem_dia():
    serie = [
        {"date": "2026-11-10", "value": 100.0},
        {"date": "2026-11-11", "value": 101.0},
        {"date": "2026-11-12", "value": 102.0},
    ]
    c = collect.compute_changes(serie, "pct", "daily")
    assert c["day"] == round((102.0 - 101.0) / 101.0 * 100, 2)


# ----- IPCA acumulado 12 meses -----
def test_ipca_acum_12m():
    serie = [{"date": f"2026-{m:02d}-01", "value": 0.5} for m in range(1, 13)]
    assert collect.ipca_acum_12m(serie) == round(((1.005 ** 12) - 1) * 100, 2)


# ----- Regra avaliada em R$/saca (nao em US¢) -----
def _price_view(ind):
    if ind.get("alt_brl"):
        a = ind["alt_brl"]
        return {"value": a["value"], "changes": a.get("changes", {}),
                "acum_12m": ind.get("acum_12m"), "stale": a.get("stale") or ind.get("fonte_velha")}
    return {"value": ind.get("value"), "changes": ind.get("changes", {}),
            "acum_12m": ind.get("acum_12m"), "stale": ind.get("fonte_velha")}


_OPS = {"<": lambda a, b: a < b, ">": lambda a, b: a > b,
        "<=": lambda a, b: a <= b, ">=": lambda a, b: a >= b}


def _fires(regra, indicators):
    for cond in regra["quando"]:
        view = _price_view(indicators[cond["indicador"]])
        if view["value"] is None or view["stale"]:
            return False
        campo = cond["campo"]
        if campo == "value":
            val = view["value"]
        elif campo == "acum_12m":
            val = view.get("acum_12m")
        else:
            val = view["changes"].get(campo.split(".")[1])
        if val is None or not _OPS[cond["operador"]](val, cond["limiar"]):
            return False
    return True


def _regra(rid):
    cfg = json.load(open(os.path.join(ROOT, "config", "thresholds.json"), encoding="utf-8"))
    return next(r for r in cfg["regras"] if r["id"] == rid)


def test_milho_em_queda_usa_rs_saca():
    regra = _regra("milho_brl_queda")  # dispara com changes.month < -4 (em R$/saca)
    # Chicago caindo (-7%) mas R$/saca subindo (+3,9%): a regra NAO deve disparar.
    ind_sobe = {"milho": {"value": 445, "changes": {"month": -7.0}, "fonte_velha": False,
                          "alt_brl": {"value": 59, "changes": {"month": 3.9}, "stale": False}}}
    assert _fires(regra, ind_sobe) is False
    # R$/saca realmente caindo (-6%): a regra deve disparar.
    ind_cai = {"milho": {"value": 445, "changes": {"month": 2.0}, "fonte_velha": False,
                         "alt_brl": {"value": 55, "changes": {"month": -6.0}, "stale": False}}}
    assert _fires(regra, ind_cai) is True


def test_regra_nao_dispara_com_fonte_velha():
    regra = _regra("milho_brl_queda")
    ind = {"milho": {"value": 445, "changes": {"month": -7}, "fonte_velha": False,
                     "alt_brl": {"value": 55, "changes": {"month": -6.0}, "stale": True}}}
    assert _fires(regra, ind) is False  # insumo desatualizado -> nao dispara


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print("ok:", fn.__name__)
    print(f"\n{len(fns)} testes passaram.")
