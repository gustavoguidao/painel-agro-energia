# -*- coding: utf-8 -*-
"""
Coletor de dados do Dashboard Agro + Energia Solar.

Roda no GitHub Actions (cron) ou localmente. Para cada indicador:
  - busca a serie historica na fonte gratuita,
  - mescla no historico versionado (data/history.json),
  - calcula valor atual e variacoes (dia/mes/ano),
  - em caso de falha, usa cache ou um valor configuravel (nunca inventa, nunca quebra).

Gera:
  data/latest.json   -> valores atuais, variacoes, noticias, metadados
  data/history.json  -> series historicas por indicador (para os graficos)

Para ADICIONAR/REMOVER um indicador: edite a lista REGISTRY mais abaixo.
Para ADICIONAR/REMOVER um feed de noticias: edite config/feeds.json.
Para ajustar limiares das recomendacoes: edite config/thresholds.json.
"""

import json
import os
import re
import sys
import traceback
from datetime import date, datetime, timedelta, timezone
from xml.etree import ElementTree as ET

import requests
from requests.adapters import HTTPAdapter

try:
    from urllib3.util.retry import Retry
except Exception:  # pragma: no cover
    from requests.packages.urllib3.util.retry import Retry  # type: ignore

# ----------------------------------------------------------------------------
# Caminhos
# ----------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT, "config")
DATA_DIR = os.path.join(ROOT, "data")

BRT = timezone(timedelta(hours=-3))  # horario de Brasilia (sem DST desde 2019)

HTTP_TIMEOUT = 25


# ----------------------------------------------------------------------------
# HTTP com retry/backoff e User-Agent generico (sem dados pessoais)
# ----------------------------------------------------------------------------
def make_session():
    s = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    s.headers.update({
        "User-Agent": "AgroEnergiaDashboard/1.0 (coletor de dados publicos)",
        "Accept": "application/json, text/xml, text/csv, */*",
    })
    return s


def get_json(s, url, params=None):
    r = s.get(url, params=params, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_text(s, url, params=None):
    r = s.get(url, params=params, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return r.text


# ----------------------------------------------------------------------------
# Utilidades de serie temporal
# ----------------------------------------------------------------------------
def _d(s):
    return date.fromisoformat(s)


def merge_series(old, new, max_points=1200):
    """Mescla pontos (dedupe por data), ordena asc e limita o tamanho."""
    d = {p["date"]: p["value"] for p in (old or []) if p.get("value") is not None}
    for p in (new or []):
        if p.get("value") is not None:
            d[p["date"]] = p["value"]
    merged = [{"date": k, "value": d[k]} for k in sorted(d)]
    return merged[-max_points:]


def value_on_or_before(series, target_iso):
    chosen = None
    for p in series:
        if p["date"] <= target_iso:
            chosen = p
        else:
            break
    return chosen


def compute_changes(series, change_type):
    """Variacao dia/mes/ano. 'pct' = percentual; 'pp' = pontos (diferenca)."""
    out = {"day": None, "month": None, "year": None}
    if not series:
        return out
    cur = series[-1]["value"]
    cur_date = _d(series[-1]["date"])

    def diff(prev_val):
        if prev_val is None or cur is None:
            return None
        if change_type == "pp":
            return round(cur - prev_val, 4)
        if prev_val == 0:
            return None
        return round((cur - prev_val) / prev_val * 100, 2)

    # dia = ponto anterior distinto
    if len(series) >= 2:
        out["day"] = diff(series[-2]["value"])
    # mes ~30 dias; ano ~365 dias
    m = value_on_or_before(series, (cur_date - timedelta(days=30)).isoformat())
    if m:
        out["month"] = diff(m["value"])
    y = value_on_or_before(series, (cur_date - timedelta(days=365)).isoformat())
    if y:
        out["year"] = diff(y["value"])
    return out


# ----------------------------------------------------------------------------
# FONTES
# ----------------------------------------------------------------------------
def fetch_bcb_sgs(s, cfg, code, transform=None):
    """Banco Central - API SGS (JSON). Retorna serie [{date,value}]."""
    end = date.today()
    start = end - timedelta(days=cfg["history_days"] + 5)
    url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"
    params = {
        "formato": "json",
        "dataInicial": start.strftime("%d/%m/%Y"),
        "dataFinal": end.strftime("%d/%m/%Y"),
    }
    raw = get_json(s, url, params)
    out = []
    for row in raw:
        try:
            dd, mm, yyyy = row["data"].split("/")
            v = float(str(row["valor"]).replace(",", "."))
            if transform:
                v = transform(v)
            out.append({"date": f"{yyyy}-{mm}-{dd}", "value": round(v, 4)})
        except Exception:
            continue
    if not out:
        raise ValueError("serie BCB vazia")
    return out


def cdi_annualize(daily_pct):
    """CDI diario (% a.d.) -> anualizado base 252."""
    return (((1 + daily_pct / 100) ** 252) - 1) * 100


def fetch_awesome_fx(s, cfg, pair):
    """AwesomeAPI - cotacao diaria. pair ex.: 'USD-BRL'. Ultimo ponto e quase tempo real."""
    n = min(cfg["history_days"], 360)  # endpoint diario limita o historico
    url = f"https://economia.awesomeapi.com.br/json/daily/{pair}/{n}"
    raw = get_json(s, url)
    out = []
    for row in raw:
        try:
            ts = int(row["timestamp"])
            dt = datetime.fromtimestamp(ts, tz=BRT).date().isoformat()
            v = float(row["bid"])
            out.append({"date": dt, "value": round(v, 4)})
        except Exception:
            continue
    if not out:
        raise ValueError("serie FX vazia")
    return out


def fetch_commodity(s, cfg, yahoo_symbol, stooq_symbol=None):
    """Futuros via Yahoo Finance (chart API). Fallback: Stooq CSV."""
    # 1) Yahoo
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}"
        j = get_json(s, url, params={"range": "1y", "interval": "1d"})
        res = j["chart"]["result"][0]
        ts = res["timestamp"]
        closes = res["indicators"]["quote"][0]["close"]
        out = []
        for t, c in zip(ts, closes):
            if c is None:
                continue
            dt = datetime.fromtimestamp(int(t), tz=BRT).date().isoformat()
            out.append({"date": dt, "value": round(float(c), 4)})
        if out:
            return out
    except Exception:
        pass
    # 2) Stooq CSV (fallback)
    if stooq_symbol:
        txt = get_text(s, "https://stooq.com/q/d/l/", params={"s": stooq_symbol, "i": "d"})
        out = []
        for line in txt.strip().splitlines()[1:]:
            parts = line.split(",")
            if len(parts) < 5:
                continue
            try:
                out.append({"date": parts[0], "value": round(float(parts[4]), 4)})
            except Exception:
                continue
        if out:
            return out
    raise ValueError(f"commodity {yahoo_symbol} indisponivel (Yahoo e Stooq)")


def fetch_solar(s, cfg):
    """Irradiacao solar (soma de radiacao de ondas curtas) via Open-Meteo. MJ/m2 -> kWh/m2/dia."""
    loc = cfg["solar_location"]
    end = date.today()
    start = end - timedelta(days=cfg["history_days"])
    pts = {}
    # historico (archive tem ~2-5 dias de atraso)
    try:
        j = get_json(s, "https://archive-api.open-meteo.com/v1/archive", params={
            "latitude": loc["lat"], "longitude": loc["lon"],
            "start_date": start.isoformat(), "end_date": end.isoformat(),
            "daily": "shortwave_radiation_sum", "timezone": "auto",
        })
        for t, v in zip(j["daily"]["time"], j["daily"]["shortwave_radiation_sum"]):
            if v is not None:
                pts[t] = v / 3.6
    except Exception:
        pass
    # dias recentes via forecast (preenche a ponta)
    try:
        j = get_json(s, "https://api.open-meteo.com/v1/forecast", params={
            "latitude": loc["lat"], "longitude": loc["lon"],
            "daily": "shortwave_radiation_sum", "past_days": 31, "forecast_days": 1,
            "timezone": "auto",
        })
        for t, v in zip(j["daily"]["time"], j["daily"]["shortwave_radiation_sum"]):
            if v is not None:
                pts[t] = v / 3.6
    except Exception:
        pass
    if not pts:
        raise ValueError("irradiacao solar indisponivel")
    return [{"date": t, "value": round(pts[t], 3)} for t in sorted(pts)]


def fetch_cepea_boi(s, cfg):
    """Best-effort: indicador Boi Gordo CEPEA/B3 (R$/@). Fallback -> override manual."""
    url = "https://www.cepea.esalq.usp.br/br/indicador/boi-gordo.aspx"
    html = get_text(s, url)
    # procura um valor no formato brasileiro proximo a "Indicador"
    m = re.search(r"Indicador[\s\S]{0,400}?R\$\s*([\d\.]+,\d{2})", html)
    if not m:
        m = re.search(r"([\d]{3}\.[\d]{2}|[\d]{3},\d{2})", html)
    if not m:
        raise ValueError("nao foi possivel extrair o indicador CEPEA")
    v = float(m.group(1).replace(".", "").replace(",", "."))
    today = date.today().isoformat()
    return [{"date": today, "value": round(v, 2)}]


def fetch_ons_cmo(s, cfg, submercado="SE"):
    """PLD/preco de energia via ONS - CMO Semanal (Custo Marginal de Operacao, base do PLD).
    CSV publico e estavel por ano. Usa a coluna val_cmomediasemanal do submercado escolhido
    (SE/CO por padrao). Se falhar, o coletor cai no valor manual de config/settings.json."""
    years = [date.today().year, date.today().year - 1]
    pts = {}
    for y in years:
        url = f"https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/cmo_se/CMO_SEMANAL_{y}.csv"
        try:
            txt = get_text(s, url)
        except Exception:
            continue
        lines = txt.splitlines()
        if not lines:
            continue
        header = [h.strip() for h in lines[0].split(";")]
        try:
            i_sub = header.index("id_subsistema")
            i_date = header.index("din_instante")
            i_val = header.index("val_cmomediasemanal")
        except ValueError:
            continue
        for ln in lines[1:]:
            cols = ln.split(";")
            if len(cols) <= max(i_sub, i_date, i_val):
                continue
            if cols[i_sub].strip() != submercado:
                continue
            d = cols[i_date].strip()[:10]
            try:
                v = float(cols[i_val].replace(",", "."))
            except Exception:
                continue
            pts[d] = v
    if not pts:
        raise ValueError("CMO/PLD (ONS) indisponivel")
    return [{"date": d, "value": round(pts[d], 2)} for d in sorted(pts)]


# ----------------------------------------------------------------------------
# REGISTRO DE INDICADORES  (adicione/remova itens aqui)
# ----------------------------------------------------------------------------
REGISTRY = [
    # --- Macro e juros ---
    {"key": "selic", "label": "Selic (meta)", "unit": "% a.a.", "group": "macro",
     "change_type": "pp", "source": "BCB SGS 432",
     "source_url": "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados?formato=json",
     "fetch": lambda s, c: fetch_bcb_sgs(s, c, 432)},
    {"key": "cdi", "label": "CDI (anualizado)", "unit": "% a.a.", "group": "macro",
     "change_type": "pp", "source": "BCB SGS 12 (anualizado)",
     "source_url": "https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados?formato=json",
     "fetch": lambda s, c: fetch_bcb_sgs(s, c, 12, transform=cdi_annualize)},
    {"key": "ipca", "label": "IPCA (mensal)", "unit": "% no mes", "group": "macro",
     "change_type": "pp", "source": "BCB SGS 433",
     "source_url": "https://api.bcb.gov.br/dados/serie/bcdata.sgs.433/dados?formato=json",
     "fetch": lambda s, c: fetch_bcb_sgs(s, c, 433)},

    # --- Cambio ---
    {"key": "usd", "label": "Dolar (USD/BRL)", "unit": "R$", "group": "cambio",
     "change_type": "pct", "source": "AwesomeAPI (USD-BRL)",
     "source_url": "https://economia.awesomeapi.com.br/json/last/USD-BRL",
     "fetch": lambda s, c: fetch_awesome_fx(s, c, "USD-BRL")},
    {"key": "eur", "label": "Euro (EUR/BRL)", "unit": "R$", "group": "cambio",
     "change_type": "pct", "source": "AwesomeAPI (EUR-BRL)",
     "source_url": "https://economia.awesomeapi.com.br/json/last/EUR-BRL",
     "fetch": lambda s, c: fetch_awesome_fx(s, c, "EUR-BRL")},

    # --- Commodities agro (futuros; unidade indicada) ---
    {"key": "soja", "label": "Soja (futuro CBOT)", "unit": "US¢/bushel", "group": "commodities",
     "change_type": "pct", "source": "Yahoo Finance ZS=F",
     "source_url": "https://finance.yahoo.com/quote/ZS=F",
     "fetch": lambda s, c: fetch_commodity(s, c, "ZS=F", "zs.f")},
    {"key": "milho", "label": "Milho (futuro CBOT)", "unit": "US¢/bushel", "group": "commodities",
     "change_type": "pct", "source": "Yahoo Finance ZC=F",
     "source_url": "https://finance.yahoo.com/quote/ZC=F",
     "fetch": lambda s, c: fetch_commodity(s, c, "ZC=F", "zc.f")},
    {"key": "cafe", "label": "Café (futuro ICE)", "unit": "US¢/lb", "group": "commodities",
     "change_type": "pct", "source": "Yahoo Finance KC=F",
     "source_url": "https://finance.yahoo.com/quote/KC=F",
     "fetch": lambda s, c: fetch_commodity(s, c, "KC=F", "kc.f")},
    {"key": "acucar", "label": "Açúcar (futuro ICE #11)", "unit": "US¢/lb", "group": "commodities",
     "change_type": "pct", "source": "Yahoo Finance SB=F",
     "source_url": "https://finance.yahoo.com/quote/SB=F",
     "fetch": lambda s, c: fetch_commodity(s, c, "SB=F", "sb.f")},
    {"key": "algodao", "label": "Algodão (futuro ICE)", "unit": "US¢/lb", "group": "commodities",
     "change_type": "pct", "source": "Yahoo Finance CT=F",
     "source_url": "https://finance.yahoo.com/quote/CT=F",
     "fetch": lambda s, c: fetch_commodity(s, c, "CT=F", "ct.f")},
    {"key": "boi_gordo", "label": "Boi gordo (CEPEA/B3)", "unit": "R$/@", "group": "commodities",
     "change_type": "pct", "source": "CEPEA/ESALQ (a vista)",
     "source_url": "https://www.cepea.esalq.usp.br/br/indicador/boi-gordo.aspx",
     "fetch": lambda s, c: fetch_cepea_boi(s, c)},

    # --- Energia ---
    {"key": "pld", "label": "CMO/PLD (SE/CO)", "unit": "R$/MWh", "group": "energia",
     "change_type": "pct", "source": "ONS – CMO Semanal (SE/CO)",
     "source_url": "https://dados.ons.org.br/dataset/cmo-semanal",
     "note": "Custo Marginal de Operação semanal (base do PLD).",
     "fetch": lambda s, c: fetch_ons_cmo(s, c, "SE")},
    {"key": "solar", "label": "Irradiação solar", "unit": "kWh/m²/dia", "group": "energia",
     "change_type": "pct", "source": "Open-Meteo",
     "source_url": "https://open-meteo.com",
     "fetch": lambda s, c: fetch_solar(s, c)},
]

GROUPS = [
    {"id": "macro", "label": "Macro e juros"},
    {"id": "cambio", "label": "Câmbio"},
    {"id": "commodities", "label": "Commodities agro"},
    {"id": "energia", "label": "Energia"},
]

# Conversao de futuros (US cents) para R$/saca de 60 kg, usando o cambio do dia.
# 'bushel': preco em US cents/bushel -> kg por bushel do grao. 'lb': US cents/libra.
LB_KG = 0.453592
SACA_KG = 60.0
SACA_CONV = {
    "soja": {"type": "bushel", "kg": 27.2155},
    "milho": {"type": "bushel", "kg": 25.4012},
    "cafe": {"type": "lb"},
}


def to_brl_saca(cents, usd, conv):
    """US cents (por bushel ou libra) -> R$/saca de 60 kg."""
    usd_per_unit = cents / 100.0
    if conv["type"] == "bushel":
        usd_per_kg = usd_per_unit / conv["kg"]
    else:  # lb
        usd_per_kg = usd_per_unit / LB_KG
    return usd_per_kg * SACA_KG * usd


# ----------------------------------------------------------------------------
# Noticias (RSS)
# ----------------------------------------------------------------------------
def _parse_pubdate(text):
    if not text:
        return None
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            return datetime.strptime(text.strip(), fmt)
        except Exception:
            continue
    return None


def fetch_news(s, feeds_cfg):
    items = []
    for feed in feeds_cfg.get("feeds", []):
        try:
            xml = get_text(s, feed["url"])
            root = ET.fromstring(xml)
            for it in root.iter("item"):
                title = (it.findtext("title") or "").strip()
                link = (it.findtext("link") or "").strip()
                if not title or not link:
                    continue
                src_el = it.find("source")
                source = (src_el.text.strip() if src_el is not None and src_el.text else feed.get("name", ""))
                pub = _parse_pubdate(it.findtext("pubDate"))
                items.append({
                    "title": title,
                    "link": link,
                    "source": source,
                    "categoria": feed.get("categoria", ""),
                    "date": pub.astimezone(BRT).isoformat() if pub else None,
                    "_sort": pub.timestamp() if pub else 0,
                })
        except Exception as e:
            print(f"  [noticias] falha no feed {feed.get('name')}: {e}")
            continue
    items.sort(key=lambda x: x["_sort"], reverse=True)
    for it in items:
        it.pop("_sort", None)
    return items[: feeds_cfg.get("max_itens", 18)]


# ----------------------------------------------------------------------------
# Leitura/escrita de arquivos
# ----------------------------------------------------------------------------
def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    cfg = load_json(os.path.join(CONFIG_DIR, "settings.json"), {})
    cfg.setdefault("history_days", 400)
    cfg.setdefault("solar_location", {"name": "Sorriso-MT", "lat": -12.545, "lon": -55.711})
    feeds_cfg = load_json(os.path.join(CONFIG_DIR, "feeds.json"), {"feeds": [], "max_itens": 18})
    overrides = (cfg.get("manual_overrides") or {})

    history = load_json(os.path.join(DATA_DIR, "history.json"), {})
    prev_latest = load_json(os.path.join(DATA_DIR, "latest.json"), {"indicators": {}})
    prev_ind = prev_latest.get("indicators", {})

    session = make_session()
    indicators = {}
    errors = []

    for item in REGISTRY:
        key = item["key"]
        base = {
            "label": item["label"], "unit": item["unit"], "group": item["group"],
            "change_type": item["change_type"], "source": item["source"],
            "source_url": item["source_url"],
        }
        try:
            series = item["fetch"](session, cfg)
            series = [p for p in series if p.get("value") is not None]
            if not series:
                raise ValueError("serie vazia")
            hist = merge_series(history.get(key, []), series)
            history[key] = hist
            last = hist[-1]
            indicators[key] = dict(base, value=last["value"], as_of=last["date"],
                                   changes=compute_changes(hist, item["change_type"]),
                                   stale=False, manual=False, note=item.get("note"))
            print(f"  [ok] {key}: {last['value']} ({last['date']}, {len(hist)} pts)")
        except Exception as e:
            errors.append(f"{key}: {e}")
            print(f"  [falha] {key}: {e}")
            ov = overrides.get(key) if isinstance(overrides, dict) else None
            if history.get(key):
                hist = history[key]
                last = hist[-1]
                indicators[key] = dict(base, value=last["value"], as_of=last["date"],
                                       changes=compute_changes(hist, item["change_type"]),
                                       stale=True, manual=False,
                                       note="Fonte indisponivel; exibindo ultimo dado em cache.")
            elif ov and isinstance(ov, dict) and "value" in ov:
                indicators[key] = dict(base, value=ov["value"], as_of=ov.get("as_of"),
                                       changes={"day": None, "month": None, "year": None},
                                       stale=True, manual=True,
                                       note=ov.get("note", "Valor configurado manualmente."))
            elif key in prev_ind:
                indicators[key] = dict(prev_ind[key], stale=True,
                                       note="Fonte indisponivel; ultimo dado conhecido.")
            else:
                indicators[key] = dict(base, value=None, as_of=None,
                                       changes={"day": None, "month": None, "year": None},
                                       stale=True, manual=False, note="Sem dados disponiveis.")

    # Conversao R$/saca (60 kg) para soja, milho e cafe, usando o historico do dolar.
    usd_hist = history.get("usd", [])
    for key, conv in SACA_CONV.items():
        if key not in indicators or not history.get(key) or not usd_hist:
            continue
        brl_series = []
        for p in history[key]:
            u = value_on_or_before(usd_hist, p["date"])
            if not u:
                continue
            brl_series.append({"date": p["date"],
                               "value": round(to_brl_saca(p["value"], u["value"], conv), 2)})
        if not brl_series:
            continue
        history[key + "_brl"] = brl_series
        last_brl = brl_series[-1]
        indicators[key]["alt_brl"] = {
            "label": "R$/saca (60kg)", "unit": "R$/sc",
            "value": last_brl["value"], "as_of": last_brl["date"],
            "changes": compute_changes(brl_series, "pct"),
            "history_key": key + "_brl",
        }

    try:
        news = fetch_news(session, feeds_cfg)
    except Exception as e:
        news = prev_latest.get("news", [])
        errors.append(f"noticias: {e}")

    out = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "timezone": cfg.get("timezone", "America/Sao_Paulo"),
        "solar_location": cfg.get("solar_location"),
        "groups": GROUPS,
        "indicators": indicators,
        "news": news,
        "errors": errors,
    }

    save_json(os.path.join(DATA_DIR, "history.json"), history)
    save_json(os.path.join(DATA_DIR, "latest.json"), out)

    ok = sum(1 for i in indicators.values() if not i.get("stale"))
    print(f"\nConcluido: {ok}/{len(REGISTRY)} indicadores ao vivo, "
          f"{len(news)} noticias, {len(errors)} avisos.")
    if errors:
        print("Avisos:", "; ".join(errors))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
