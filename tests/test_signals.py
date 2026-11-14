# -*- coding: utf-8 -*-
"""
Testes do motor de leituras v2 (Fase 3 — collector/signals.py).
Rodam com pytest OU direto:
    py -m pytest tests/ -q
    py tests/test_signals.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "collector"))

import signals as S  # noqa: E402


def _serie(vals, start="2026-01-01"):
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    return [{"date": (d0 + timedelta(days=i)).isoformat(), "value": v} for i, v in enumerate(vals)]


# ----- Métricas -----
def test_pct_change():
    s = _serie([100, 110])
    assert S.pct_change(s, 1) == 10.0


def test_percentile_extremos():
    s = _serie(list(range(1, 41)))          # 40 pontos crescentes
    pts = S.percentile_series(s, window_days=365, min_pts=30)
    assert pts[-1][1] == 100.0               # último é o maior -> topo
    assert pts[0][1] is None                 # poucas observações -> sem percentil


# ----- Histerese (debounce em banda) -----
def test_debounce_entra_so_apos_min_run():
    # um único pico não liga (min_run=2); dois seguidos ligam
    pts = [(d, v) for d, v in zip([p["date"] for p in _serie([0, 0, 0])], [95, 85, 95])]
    estado, since, _ = S.debounce_band(pts, 90, 80, 10, 20, min_run=2)
    assert estado == "neutro"
    pts2 = [(d, v) for d, v in zip([p["date"] for p in _serie([0, 0])], [95, 95])]
    estado2, since2, _ = S.debounce_band(pts2, 90, 80, 10, 20, min_run=2)
    assert estado2 == "alto" and since2 is not None


def test_debounce_sai_com_folga():
    # liga em alto e SÓ sai quando cruza o exit (folga): 85 (>80) mantém; 75 (<80) sai
    vals = [95, 95, 85, 75]
    pts = [(p["date"], v) for p, v in zip(_serie(vals), vals)]
    estado, _, estados = S.debounce_band(pts, 90, 80, 10, 20, min_run=2)
    estados_por_data = dict(estados)
    assert estados_por_data[pts[2][0]] == "alto"   # 85 ainda dentro da folga
    assert estado == "neutro"                        # 75 cruzou o exit_high


def test_freq_ano_fracao():
    estados = [("2026-11-{:02d}".format(d), "alto" if d <= 5 else "neutro") for d in range(1, 11)]
    fa = S.freq_ano(estados, "alto")
    assert fa["dias"] == 5 and fa["total"] == 10 and fa["pct"] == 50


# ----- Perfil -----
def test_roles_from_perfil():
    perfil = {"fazendas": [
        {"atividade": ["soja"], "papel": "vende"},
        {"atividade": ["gado"], "papel": "compra_vende"},
    ], "solar": {"estados": ["GO"]}}
    r = S.roles_from_perfil(perfil)
    assert r["vende_soja"] and r["compra_milho"] and r["tem_solar"]


# ----- build_signals de ponta a ponta -----
def _thr():
    return json.load(open(os.path.join(ROOT, "config", "thresholds.json"), encoding="utf-8"))


def _cfg_vende_soja():
    return {"perfil": {"fazendas": [{"atividade": ["soja"], "papel": "vende"}]}}


def test_soja_patamar_alto_dispara_positivo():
    # soja em R$/saca em máximas de 12m -> leitura "patamar alto", positivo p/ quem vende
    brl = _serie([100 + i for i in range(60)])      # crescente, último = topo
    history = {"soja_brl": brl, "soja": _serie([1000 + i for i in range(60)]),
               "usd": _serie([5.0 + i * 0.01 for i in range(60)])}
    indicators = {"soja": {"label": "Soja (futuro CBOT)", "value": 1059, "as_of": brl[-1]["date"],
                           "idade_dias": 0, "fonte_velha": False,
                           "alt_brl": {"value": brl[-1]["value"], "as_of": brl[-1]["date"],
                                       "usd_as_of": brl[-1]["date"], "stale": False}}}
    sigs, errs = S.build_signals(indicators, history, _cfg_vende_soja(), _thr())
    assert errs == []
    soja = next((s for s in sigs if s["id"] == "preco_soja"), None)
    assert soja is not None
    assert soja["estado"] == "patamar alto" and soja["severidade"] == "positivo"
    assert soja["ativo_desde"] is not None
    # a decomposição câmbio/Chicago precisa aparecer nos gatilhos
    assert any(g["metrica"] == "decomposição" for g in soja["gatilhos"])


def test_soja_desatualizada_vira_sem_leitura():
    brl = _serie([100 + i for i in range(60)])
    history = {"soja_brl": brl, "soja": _serie([1000 + i for i in range(60)]),
               "usd": _serie([5.0] * 60)}
    indicators = {"soja": {"label": "Soja", "value": 1059, "as_of": brl[-1]["date"],
                           "idade_dias": 30, "fonte_velha": True,
                           "alt_brl": {"value": brl[-1]["value"], "usd_as_of": brl[-1]["date"],
                                       "stale": True}}}
    sigs, _ = S.build_signals(indicators, history, _cfg_vende_soja(), _thr())
    soja = next((s for s in sigs if s["tema"] == "soja_preco"), None)
    assert soja is not None and soja["muted"] is True and soja["estado"] == "sem leitura"


def test_soja_cache_recente_ainda_gera_leitura():
    # fonte indisponível, mas cache recente (stale=True é só selo, fonte_velha=False):
    # a leitura de preço continua valendo (regra por idade, não por falha de fetch).
    brl = _serie([100 + i for i in range(60)])
    history = {"soja_brl": brl, "soja": _serie([1000 + i for i in range(60)]), "usd": _serie([5.0] * 60)}
    indicators = {"soja": {"label": "Soja", "value": 1059, "as_of": brl[-1]["date"], "idade_dias": 1,
                           "fonte_velha": False, "stale": True,
                           "alt_brl": {"value": brl[-1]["value"], "usd_as_of": brl[-1]["date"], "stale": False}}}
    sigs, _ = S.build_signals(indicators, history, _cfg_vende_soja(), _thr())
    soja = next((s for s in sigs if s["tema"] == "soja_preco"), None)
    assert soja is not None and soja.get("muted") is not True and soja["estado"] == "patamar alto"


def test_um_estado_por_tema():
    # nenhum tema pode aparecer duas vezes na saída (exclusão)
    brl = _serie([100 + i for i in range(60)])
    history = {"soja_brl": brl, "soja": _serie([1000 + i for i in range(60)]), "usd": _serie([5.0] * 60)}
    indicators = {"soja": {"label": "Soja", "value": 1059, "as_of": brl[-1]["date"], "idade_dias": 0,
                           "fonte_velha": False,
                           "alt_brl": {"value": brl[-1]["value"], "usd_as_of": brl[-1]["date"], "stale": False}},
                  "boi_gordo": {"label": "Boi", "value": None}}
    sigs, _ = S.build_signals(indicators, history, _cfg_vende_soja(), _thr())
    temas = [s["tema"] for s in sigs]
    assert len(temas) == len(set(temas))


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print("ok:", fn.__name__)
    print(f"\n{len(fns)} testes passaram.")
