# -*- coding: utf-8 -*-
"""
Motor de leituras v2 (Fase 3) — roda no coletor, em Python, e é testável.

Antes as leituras eram avaliadas no navegador (assets/js/recommendations.js).
Agora o coletor grava a lista `signals` em latest.json e o front apenas renderiza.

Cada leitura (sinal) traz:
  id, tema, estado (rótulo), severidade, titulo, texto (sensível ao perfil),
  gatilhos (série, métrica, valor, limiar, unidade), insumos (data de cada insumo),
  ativo_desde, freq_ano ("ocorreu em X% dos dias do último ano") e relevancia (ranking).

Princípios:
  - Nunca inventa dado. Se um insumo está desatualizado, a leitura vira "sem leitura".
  - Persistência com histerese: liga só depois de N observações seguidas (min_run) e
    desliga com folga (banda de saída diferente da de entrada). Um estado por tema.
  - Leituras de preço decompõem a variação em R$ entre Chicago e câmbio.
  - Funções puras sobre o histórico -> dá para rodar backtest (collector/backtest.py).

Os limiares ficam em config/thresholds.json -> "sinais" (provisórios; calibrados por backtest).
"""

from datetime import date, timedelta


# ----------------------------------------------------------------------------
# Métricas de série temporal (puras)
# ----------------------------------------------------------------------------
def _d(s):
    return date.fromisoformat(s)


def _val_at_or_before(series, target_iso):
    chosen = None
    for p in series:
        if p["date"] <= target_iso:
            chosen = p
        else:
            break
    return chosen["value"] if chosen else None


def pct_change(series, days):
    """Variação percentual entre o último ponto e o ponto ~`days` atrás (o mais próximo antes)."""
    if not series:
        return None
    cur = series[-1]["value"]
    cur_d = _d(series[-1]["date"])
    prev = _val_at_or_before(series, (cur_d - timedelta(days=days)).isoformat())
    if cur is None or prev in (None, 0):
        return None
    return round((cur - prev) / prev * 100, 2)


def diff_pp(series, days):
    """Diferença em pontos (p.p.) entre o último ponto e o de ~`days` atrás (ex.: Selic)."""
    if not series:
        return None
    cur = series[-1]["value"]
    cur_d = _d(series[-1]["date"])
    prev = _val_at_or_before(series, (cur_d - timedelta(days=days)).isoformat())
    if cur is None or prev is None:
        return None
    return round(cur - prev, 4)


def percentile_series(series, window_days=365, min_pts=30):
    """Para cada ponto, percentil (0..100) do valor dentro da janela móvel de `window_days`.
    Pontos com menos de `min_pts` observações na janela ficam None (sem base para o percentil)."""
    out = []
    n = len(series)
    for i in range(n):
        di = _d(series[i]["date"])
        cut = (di - timedelta(days=window_days)).isoformat()
        window = [series[j]["value"] for j in range(i + 1)
                  if series[j]["date"] >= cut and series[j]["value"] is not None]
        v = series[i]["value"]
        if v is None or len(window) < min_pts:
            out.append((series[i]["date"], None))
            continue
        cnt = sum(1 for x in window if x <= v)
        out.append((series[i]["date"], round(cnt / len(window) * 100, 1)))
    return out


def change_series(series, days, mode="pct"):
    """Série de (data, variação) medida contra ~`days` atrás, para cada ponto. mode: pct | pp."""
    out = []
    for i in range(len(series)):
        sub = series[:i + 1]
        out.append((series[i]["date"],
                    pct_change(sub, days) if mode == "pct" else diff_pp(sub, days)))
    return out


# ----------------------------------------------------------------------------
# Histerese: debounce em banda (entra depois de min_run; sai com folga)
# ----------------------------------------------------------------------------
def debounce_band(points, enter_high, exit_high, enter_low, exit_low, min_run=2):
    """Recebe [(data, métrica)] e devolve (estado_atual, ativo_desde, estados[]).

    Estados: "alto", "baixo", "neutro".
      - entra em "alto" se a métrica >= enter_high por `min_run` observações seguidas;
        só sai quando cair abaixo de exit_high (folga). Idem, espelhado, para "baixo".
    `estados` é a lista [(data, estado)] para calcular frequência e número de oscilações.
    """
    state = "neutro"
    since = None
    run_hi = run_lo = 0
    estados = []
    for d, m in points:
        if m is None:
            run_hi = run_lo = 0
            estados.append((d, state))
            continue
        run_hi = run_hi + 1 if m >= enter_high else 0
        run_lo = run_lo + 1 if m <= enter_low else 0
        new = state
        if state == "alto":
            if m < exit_high:
                new = "baixo" if run_lo >= min_run else "neutro"
        elif state == "baixo":
            if m > exit_low:
                new = "alto" if run_hi >= min_run else "neutro"
        else:  # neutro
            if run_hi >= min_run:
                new = "alto"
            elif run_lo >= min_run:
                new = "baixo"
        if new != state:
            state = new
            since = d if new != "neutro" else None
        estados.append((d, state))
    return state, since, estados


def freq_ano(estados, alvo):
    """Fração dos últimos 365 dias em que o estado foi `alvo`."""
    if not estados:
        return None
    last = _d(estados[-1][0])
    cut = (last - timedelta(days=365)).isoformat()
    win = [st for dd, st in estados if dd >= cut]
    if not win:
        return None
    cnt = sum(1 for st in win if st == alvo)
    return {"pct": round(cnt / len(win) * 100), "dias": cnt, "total": len(win)}


def num_oscilacoes(estados, alvo):
    """Quantas vezes o estado `alvo` ligou (transições neutro/outro -> alvo) no último ano."""
    if not estados:
        return 0
    last = _d(estados[-1][0])
    cut = (last - timedelta(days=365)).isoformat()
    win = [st for dd, st in estados if dd >= cut]
    n = 0
    prev = None
    for st in win:
        if st == alvo and prev != alvo:
            n += 1
        prev = st
    return n


# ----------------------------------------------------------------------------
# Perfil do dono -> papéis que mudam o texto das leituras
# ----------------------------------------------------------------------------
def roles_from_perfil(perfil):
    fz = (perfil or {}).get("fazendas") or []
    ativ = set()
    for f in fz:
        for a in (f.get("atividade") or []):
            ativ.add(a)
    return {
        "vende_soja": any("soja" in (f.get("atividade") or []) for f in fz),
        "vende_milho": any("milho" in (f.get("atividade") or []) for f in fz),
        "compra_milho": "gado" in ativ,   # gado consome milho (ração/confinamento)
        "cria_gado": "gado" in ativ,
        "tem_solar": bool((perfil or {}).get("solar")),
    }


# ----------------------------------------------------------------------------
# Helpers de montagem
# ----------------------------------------------------------------------------
def _insumo(indicators, key, nome, use_usd_asof=False):
    ind = indicators.get(key) or {}
    as_of = ind.get("as_of")
    if use_usd_asof:
        alt = ind.get("alt_brl") or {}
        as_of = alt.get("usd_as_of") or as_of
    return {"nome": nome, "as_of": as_of, "idade_dias": ind.get("idade_dias")}


def _is_stale(ind):
    # Bloqueia a leitura pela REGRA DE IDADE (fonte_velha): um dado em cache mas ainda
    # recente (stale=True só para o selo "em cache") continua valendo para a leitura.
    if not ind or ind.get("value") is None:
        return True
    return bool(ind.get("fonte_velha"))


def _sem_leitura(sig_id, tema, titulo, motivo, insumos):
    return {
        "id": sig_id, "tema": tema, "estado": "sem leitura", "severidade": "neutro",
        "muted": True, "titulo": titulo,
        "texto": f"Sem leitura no momento: {motivo}. Nada é estimado enquanto o insumo não atualiza.",
        "gatilhos": [], "insumos": insumos, "ativo_desde": None, "freq_ano": None,
        "relevancia": 0,
    }


_SEV_PESO = {"alerta": 3, "positivo": 2, "info": 1, "neutro": 0}


def _relevancia(severidade, magnitude):
    return _SEV_PESO.get(severidade, 0) * 1000 + round(abs(magnitude or 0))


# ----------------------------------------------------------------------------
# Leituras de PREÇO (soja, milho) — percentil em R$/saca + decomposição câmbio/Chicago
# ----------------------------------------------------------------------------
def sig_preco_percentil(key, label, tema, indicators, history, cfg, roles):
    ind = indicators.get(key)
    if not ind:
        return None
    serie_brl = history.get(key + "_brl") or []
    if len(serie_brl) < 40:
        return None
    p = cfg
    pts = percentile_series(serie_brl, p.get("janela_dias", 365))
    estado, since, estados = debounce_band(
        pts, p["enter_high"], p["exit_high"], p["enter_low"], p["exit_low"], p.get("min_run", 2))
    if estado == "neutro":
        return None

    alt = ind.get("alt_brl") or {}
    if _is_stale(ind) or alt.get("stale"):
        return _sem_leitura(f"preco_{key}", tema, f"{label} (R$/saca)",
                            "preço ou dólar desatualizado",
                            [_insumo(indicators, key, label),
                             _insumo(indicators, key, "Dólar PTAX", use_usd_asof=True)])

    cur_pct = pts[-1][1]
    alto = estado == "alto"
    # Decomposição da variação em R$ entre Chicago (US¢) e câmbio (PTAX), na janela decomp_dias.
    dd = p.get("decomp_dias", 90)
    var_brl = pct_change(serie_brl, dd)
    var_usd = pct_change(history.get(key) or [], dd)
    var_fx = pct_change(history.get("usd") or [], dd)
    decomp = _texto_decomposicao(label, var_brl, var_usd, var_fx, dd)

    # Texto sensível ao perfil (quem vende x quem compra).
    if key == "soja":
        if alto:
            lado = "Para quem vende soja, é um patamar de receita mais favorável — compare com a base da sua praça antes de qualquer decisão."
            severidade = "positivo"
        else:
            lado = "Para quem vende soja, é um patamar de receita baixo. Evite decidir venda só pela paridade: confira a base da praça."
            severidade = "alerta"
    else:  # milho
        if alto:
            lado = ("Para quem compra milho (ração, confinamento), encarece o custo; "
                    "para quem vende, melhora a receita.") if roles.get("compra_milho") else \
                   "Para quem vende milho, é um patamar de receita mais favorável."
            severidade = "alerta" if roles.get("compra_milho") else "positivo"
        else:
            lado = ("Para quem compra milho (ração, confinamento), o custo de insumo tende a aliviar; "
                    "para quem vende, é o oposto.") if roles.get("compra_milho") else \
                   "Para quem vende milho, é um patamar de receita baixo."
            severidade = "positivo" if roles.get("compra_milho") else "alerta"

    estado_lbl = "patamar alto" if alto else "patamar baixo"
    titulo = f"{label} em {estado_lbl} (R$/saca)"
    texto = (f"A paridade de {label.lower()} em R$/saca está no {estado_lbl} dos últimos 12 meses "
             f"(percentil {cur_pct:.0f}). {decomp} {lado}")

    gat = [{
        "serie": f"{label} — paridade R$/saca", "metrica": "percentil 12m",
        "valor": cur_pct, "limiar": (f">= {p['enter_high']}" if alto else f"<= {p['enter_low']}"),
        "unidade": "%",
    }, {
        "serie": f"Variação {dd}d em R$", "metrica": "decomposição",
        "valor": var_brl, "limiar": f"Chicago {_fmt(var_usd)}% · dólar {_fmt(var_fx)}%",
        "unidade": "%",
    }]
    return {
        "id": f"preco_{key}", "tema": tema, "estado": estado_lbl, "severidade": severidade,
        "titulo": titulo, "texto": texto, "gatilhos": gat,
        "insumos": [_insumo(indicators, key, f"{label} (futuro)"),
                    _insumo(indicators, key, "Dólar PTAX", use_usd_asof=True)],
        "ativo_desde": since, "freq_ano": freq_ano(estados, estado),
        "oscilacoes_ano": num_oscilacoes(estados, estado),
        "relevancia": _relevancia(severidade, (cur_pct or 50) - 50),
    }


def _texto_decomposicao(label, var_brl, var_usd, var_fx, dd):
    if var_brl is None:
        return ""
    partes = []
    if var_usd is not None:
        partes.append(f"Chicago {_fmt(var_usd)}%")
    if var_fx is not None:
        partes.append(f"dólar {_fmt(var_fx)}%")
    corpo = ", ".join(partes)
    # Qual lado explica mais o movimento em R$?
    origem = ""
    if var_usd is not None and var_fx is not None:
        origem = " — o movimento vem mais do câmbio." if abs(var_fx) > abs(var_usd) + 1 else (
                 " — o movimento vem mais de Chicago." if abs(var_usd) > abs(var_fx) + 1 else
                 " — câmbio e Chicago pesam parecido.")
    if not corpo:
        return f"Em {dd} dias: {_fmt(var_brl)}% em R$."
    return f"Em {dd} dias: {_fmt(var_brl)}% em R$ ({corpo}){origem}"


def _fmt(v):
    if v is None:
        return "—"
    return ("+" if v > 0 else "") + f"{v:.1f}".replace(".", ",")


# ----------------------------------------------------------------------------
# Boi gordo — honesto: sem fonte automática (não gera leitura, não estima)
# ----------------------------------------------------------------------------
def sig_boi_sem_fonte(indicators):
    if "boi_gordo" not in indicators:
        return None
    return {
        "id": "boi_sem_fonte", "tema": "boi_preco", "estado": "sem fonte", "severidade": "neutro",
        "muted": True, "titulo": "Boi gordo sem leitura automática",
        "texto": ("Não há fonte automática gratuita para o preço do boi no momento "
                  "(o scraping do CEPEA foi removido por licença). Uma fonte regional (Conab) "
                  "está prevista. Enquanto isso, nada é estimado para o boi."),
        "gatilhos": [], "insumos": [], "ativo_desde": None, "freq_ano": None, "relevancia": 0,
    }


# ----------------------------------------------------------------------------
# Câmbio (USD/BRL) — movimento de 30 e 90 dias, com os dois lados
# ----------------------------------------------------------------------------
def sig_cambio(indicators, history, cfg, roles):
    ind = indicators.get("usd")
    serie = history.get("usd") or []
    if not ind or len(serie) < 40:
        return None
    jv = cfg.get("janela_var", 90)
    metric = change_series(serie, jv, "pct")
    estado, since, estados = debounce_band(
        metric, cfg["enter_high"], cfg["exit_high"], cfg["enter_low"], cfg["exit_low"], cfg.get("min_run", 2))
    if estado == "neutro":
        return None
    if _is_stale(ind):
        return _sem_leitura("cambio", "cambio", "Dólar (PTAX)", "dólar desatualizado",
                            [_insumo(indicators, "usd", "Dólar PTAX")])

    var90 = pct_change(serie, jv)
    var30 = pct_change(serie, 30)
    alta = estado == "alto"
    estado_lbl = "em alta" if alta else "em queda"
    if alta:
        texto = (f"O dólar (PTAX) subiu nos últimos {jv} dias ({_fmt(var90)}% em {jv}d, "
                 f"{_fmt(var30)}% em 30d). Dois lados: encarece insumos e equipamento solar importado "
                 f"e, ao mesmo tempo, melhora a receita em reais do grão exportado.")
    else:
        texto = (f"O dólar (PTAX) caiu nos últimos {jv} dias ({_fmt(var90)}% em {jv}d, "
                 f"{_fmt(var30)}% em 30d). Insumos e equipamento importado tendem a ficar mais baratos; "
                 f"a receita em reais da exportação tende a ceder.")
    gat = [{"serie": "Dólar PTAX", "metrica": f"variação {jv}d", "valor": var90,
            "limiar": (f">= {cfg['enter_high']}" if alta else f"<= {cfg['enter_low']}"), "unidade": "%"},
           {"serie": "Dólar PTAX", "metrica": "variação 30d", "valor": var30, "limiar": "—", "unidade": "%"}]
    return {
        "id": "cambio", "tema": "cambio", "estado": estado_lbl, "severidade": "info",
        "titulo": f"Dólar {estado_lbl} ({jv} dias)", "texto": texto, "gatilhos": gat,
        "insumos": [_insumo(indicators, "usd", "Dólar PTAX")],
        "ativo_desde": since, "freq_ano": freq_ano(estados, estado),
        "oscilacoes_ano": num_oscilacoes(estados, estado),
        "relevancia": _relevancia("info", var90),
    }


# ----------------------------------------------------------------------------
# Juros (Selic) — estado único, degrau de ~90 dias
# ----------------------------------------------------------------------------
def sig_juros(indicators, history, cfg):
    ind = indicators.get("selic")
    serie = history.get("selic") or []
    if not ind or len(serie) < 20:
        return None
    jv = cfg.get("janela_var", 90)
    metric = change_series(serie, jv, "pp")
    estado, since, estados = debounce_band(
        metric, cfg["enter_high"], cfg["exit_high"], cfg["enter_low"], cfg["exit_low"], cfg.get("min_run", 1))
    if estado == "neutro":
        return None
    if _is_stale(ind):
        return _sem_leitura("juros", "juros", "Selic", "Selic desatualizada",
                            [_insumo(indicators, "selic", "Selic (meta)")])
    var = diff_pp(serie, jv)
    alta = estado == "alto"
    if alta:
        severidade = "alerta"
        texto = (f"A Selic subiu {_fmt(var)} p.p. nos últimos {jv} dias. O custo de capital está mais alto: "
                 f"projetos novos passam a exigir retorno maior e a parcela de financiamento do cliente "
                 f"(inclusive de sistemas solares) fica mais cara.")
        estado_lbl = "em alta"
    else:
        severidade = "positivo"
        texto = (f"A Selic recuou {_fmt(var)} p.p. nos últimos {jv} dias. O custo de crédito de investimento "
                 f"tende a ceder — vale comparar o custo de financiamento atual com o de meses atrás antes "
                 f"de decidir CAPEX.")
        estado_lbl = "em queda"
    gat = [{"serie": "Selic (meta)", "metrica": f"variação {jv}d", "valor": var,
            "limiar": (f">= {cfg['enter_high']}" if alta else f"<= {cfg['enter_low']}"), "unidade": "p.p."}]
    return {
        "id": "juros", "tema": "juros", "estado": estado_lbl, "severidade": severidade,
        "titulo": f"Selic {estado_lbl} ({jv} dias)", "texto": texto, "gatilhos": gat,
        "insumos": [_insumo(indicators, "selic", "Selic (meta)")],
        "ativo_desde": since, "freq_ano": freq_ano(estados, estado),
        "oscilacoes_ano": num_oscilacoes(estados, estado),
        "relevancia": _relevancia(severidade, (var or 0) * 100),
    }


# ----------------------------------------------------------------------------
# Chuva por ponto — veranico (seco) ou excesso, contra a normal sazonal
# ----------------------------------------------------------------------------
def sig_chuva(key, indicators, history, cfg):
    ind = indicators.get(key)
    if not ind:
        return None
    ch = ind.get("chuva") or {}
    cidade = ch.get("cidade") or ind.get("label")
    pct_serie = history.get(key + "_pct") or []
    if pct_serie:
        metric = [(p["date"], p["value"]) for p in pct_serie]
        estado, since, estados = debounce_band(
            metric, cfg["enter_high"], cfg["exit_high"], cfg["enter_low"], cfg["exit_low"], cfg.get("min_run", 3))
        fa = freq_ano(estados, estado)
        osc = num_oscilacoes(estados, estado)
    else:  # sem série de % da normal: usa só o retrato atual, sem inventar histórico
        cur = ch.get("pct_normal")
        estado = ("baixo" if (cur is not None and cur <= cfg["enter_low"]) else
                  "alto" if (cur is not None and cur >= cfg["enter_high"]) else "neutro")
        since, fa, osc = None, None, 0
    if estado == "neutro":
        return None
    if ind.get("fonte_velha"):   # chuva velha: não arrisca leitura
        return None

    cur = ch.get("pct_normal")
    seco = estado == "baixo"
    severidade = "alerta"
    if seco:
        estado_lbl = "abaixo da normal"
        texto = (f"A chuva acumulada em 30 dias em {cidade} está em {cur}% da normal do período — "
                 f"abaixo do normal (possível veranico). Confira a fase da cultura/pasto antes de decidir "
                 f"manejo, plantio ou suplementação.")
    else:
        estado_lbl = "acima da normal"
        texto = (f"A chuva acumulada em 30 dias em {cidade} está em {cur}% da normal do período — "
                 f"acima do normal. Atenção a excesso hídrico (plantio, pulverização, colheita, "
                 f"doenças fúngicas).")
    gat = [{"serie": f"Chuva 30d — {cidade}", "metrica": "% da normal sazonal", "valor": cur,
            "limiar": (f"<= {cfg['enter_low']}" if seco else f">= {cfg['enter_high']}"), "unidade": "%"},
           {"serie": "Acumulado 30d", "metrica": "observado", "valor": ch.get("acum_30"),
            "limiar": f"normal {ch.get('normal_30')}", "unidade": "mm"}]
    return {
        "id": key, "tema": key, "estado": estado_lbl, "severidade": severidade,
        "titulo": f"Chuva {estado_lbl} — {cidade}", "texto": texto, "gatilhos": gat,
        "insumos": [_insumo(indicators, key, "Open-Meteo (observado)")],
        "ativo_desde": since, "freq_ano": fa, "oscilacoes_ano": osc,
        "relevancia": _relevancia(severidade, (cur or 100) - 100),
    }


# ----------------------------------------------------------------------------
# Orquestrador
# ----------------------------------------------------------------------------
def build_signals(indicators, history, cfg, thresholds):
    """Monta a lista de leituras (ordenada por relevância) e a lista de avisos."""
    sin = (thresholds or {}).get("sinais") or {}
    perfil = (cfg or {}).get("perfil") or {}
    roles = roles_from_perfil(perfil)
    signals = []
    errors = []

    def run(fn, *args):
        try:
            sig = fn(*args)
            if sig:
                signals.append(sig)
        except Exception as e:  # pragma: no cover
            errors.append(f"{fn.__name__}: {e}")

    for key, label, tema in [("soja", "Soja", "soja_preco"), ("milho", "Milho", "milho_preco")]:
        run(sig_preco_percentil, key, label, tema, indicators, history,
            sin.get("preco_percentil", {}), roles)
    run(sig_boi_sem_fonte, indicators)
    run(sig_cambio, indicators, history, sin.get("cambio", {}), roles)
    run(sig_juros, indicators, history, sin.get("juros", {}))
    for key in ("chuva_go", "chuva_to"):
        if key in indicators:
            run(sig_chuva, key, indicators, history, sin.get("chuva", {}))

    # Um estado por tema (exclusão): mantém o de maior relevância por tema.
    por_tema = {}
    for s in signals:
        t = s.get("tema")
        if t not in por_tema or s.get("relevancia", 0) > por_tema[t].get("relevancia", 0):
            por_tema[t] = s
    out = sorted(por_tema.values(), key=lambda s: s.get("relevancia", 0), reverse=True)
    return out, errors
