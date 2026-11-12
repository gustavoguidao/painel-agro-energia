# Painel Agro + Energia Solar 🌾⚡

Dashboard web com indicadores de **agronegócio** e **energia solar** no Brasil, com
**atualização automática** por cron, **fontes 100% gratuitas** e **link público** para
compartilhar. Mostra valor atual, variação (dia/mês/ano), gráficos históricos, notícias
e um painel de **recomendações** baseado em um motor de regras transparente.

> ⚠️ As recomendações são **leituras automáticas** geradas por regras configuráveis.
> **Não** constituem recomendação ou aconselhamento financeiro.

---

## 1. Arquitetura (o quê roda onde)

Padrão escolhido: **GitHub Actions (cron) + GitHub Pages** — gratuito, estável, com link
público e histórico versionado no próprio repositório.

```
┌──────────────────────────────────────────────────────────────┐
│  GitHub Actions (cron a cada 6h) — roda no servidor do GitHub  │
│    collector/collect.py                                        │
│      • busca cada fonte gratuita (BCB, AwesomeAPI, Yahoo, ...)  │
│      • mescla no histórico e calcula variações                 │
│      • grava data/latest.json e data/history.json              │
│      • faz commit automático de volta no repositório           │
└───────────────┬────────────────────────────────────────────────┘
                │  (cada commit republica o site)
┌───────────────▼────────────────────────────────────────────────┐
│  GitHub Pages — site estático (HTML/CSS/JS)                     │
│    index.html lê os JSON e renderiza cards, gráficos (Chart.js),│
│    notícias e recomendações. Nada de servidor, nada de segredos.│
└────────────────────────────────────────────────────────────────┘
```

**Por que esse padrão e não Streamlit?** O Streamlit Community Cloud também é grátis, mas o
app "dorme" quando ocioso, coleta só quando alguém abre a página e exige storage externo
para guardar histórico. Com Actions + Pages a coleta é independente de visitas, o histórico
fica versionado no repo e o site é estático (carrega rápido e não expõe segredos).

### Estrutura de pastas

```
.
├── index.html                  # página do painel
├── assets/
│   ├── css/styles.css          # tema claro/escuro, layout responsivo
│   └── js/
│       ├── format.js           # formatação pt-BR (números, datas, variações)
│       ├── recommendations.js  # motor de regras das recomendações
│       └── app.js              # carrega os dados e desenha tudo
├── collector/
│   ├── collect.py              # coletor (REGISTRY = lista de indicadores)
│   └── requirements.txt        # dependências Python (só 'requests')
├── config/
│   ├── settings.json           # local da irradiação, janela de histórico, overrides
│   ├── feeds.json              # feeds RSS de notícias
│   └── thresholds.json         # limiares/regras das recomendações
├── data/                       # GERADO pelo coletor (versionado)
│   ├── latest.json             # valores atuais + notícias + metadados
│   └── history.json            # séries históricas (para os gráficos)
├── .github/workflows/update-data.yml   # cron + commit automático
├── .nojekyll                   # faz o Pages servir os arquivos como estão
└── README.md
```

---

## 2. Fontes usadas por indicador

| Indicador | Fonte (gratuita) | Tipo / Unidade | Observação |
|---|---|---|---|
| Selic (meta) | Banco Central — SGS série **432** | % a.a. | oficial |
| CDI (anualizado) | Banco Central — SGS série **12** | % a.a. | diário anualizado base 252 |
| IPCA (mensal) | Banco Central — SGS série **433** | % no mês | oficial |
| Dólar USD/BRL | **AwesomeAPI** (`economia.awesomeapi.com.br`) | R$ | último ponto quase em tempo real |
| Euro EUR/BRL | **AwesomeAPI** | R$ | idem |
| Soja | **Yahoo Finance** `ZS=F` (fallback Stooq) | US¢/bushel | **futuro** CBOT |
| Milho | **Yahoo Finance** `ZC=F` | US¢/bushel | **futuro** CBOT |
| Café | **Yahoo Finance** `KC=F` | US¢/lb | **futuro** ICE |
| Açúcar | **Yahoo Finance** `SB=F` | US¢/lb | **futuro** ICE nº 11 |
| Algodão | **Yahoo Finance** `CT=F` | US¢/lb | **futuro** ICE |
| Boi gordo | **CEPEA/ESALQ** (scraping) | R$/@ | à vista; fallback para valor manual |
| PLD / energia | **Configurável** (CCEE/ONS) | R$/MWh | ver nota abaixo |
| Irradiação solar | **Open-Meteo** (`shortwave_radiation_sum`) | kWh/m²/dia | sem chave |
| Notícias | **Google News RSS** por tópico | título + link | só título e link (sem texto da matéria) |

### Decisões registradas (como pedido)
- **Commodities à vista × futuro:** usamos **futuros** (Yahoo) para soja, milho, café, açúcar e
  algodão porque não há fonte à vista gratuita e estável para todas. O rótulo "futuro" e a
  unidade aparecem em cada card. O **boi gordo** usa o indicador **à vista CEPEA/B3**.
- **PLD / preço de energia:** não há uma API gratuita e estável que entregue o PLD de forma
  genérica (CCEE/ONS publicam em arquivos que mudam de formato). Seguindo o briefing, deixamos
  um **campo configurável** em `config/settings.json` (`manual_overrides.pld`) — o valor aparece
  no painel com o selo **"manual"** e a data que você definir. (Veja em
  [§6](#6-pld-energia-como-manter-atualizado) como atualizar ou automatizar.)
- **Boi gordo:** o scraping do CEPEA é *best-effort*. Se a página mudar, o painel cai para o
  valor de `manual_overrides.boi_gordo` e mostra o selo "manual".
- **Frequência:** cron a cada **6 horas** (00/06/12/18 UTC). Ajustável no workflow.
- **Irradiação solar:** ponto padrão **Sorriso-MT**. Troque em `config/settings.json`.

---

## 3. Como a atualização automática funciona

1. O arquivo `.github/workflows/update-data.yml` dispara por **cron** (a cada 6h) ou
   manualmente (botão *Run workflow* na aba **Actions**).
2. O job instala Python + `requests` e executa `python collector/collect.py`.
3. O coletor busca cada fonte, **mescla** os pontos novos no `data/history.json` (sem apagar o
   histórico) e grava o `data/latest.json`.
4. Se houver mudança, o job faz **commit e push** dos dois JSON de volta ao repositório.
5. Cada commit faz o **GitHub Pages republicar** o site — ninguém precisa rodar nada à mão.

**Robustez:** cada fonte é tratada isoladamente. Se uma falhar, o painel mostra o **último dado
em cache** (selo "desatualizado") ou o **valor configurado** (selo "manual") — nunca quebra a
página inteira nem inventa número. O coletor tem *retry* com backoff e timeouts; as notícias e
cada indicador são independentes.

---

## 4. Passo a passo para publicar do zero

> Você escolheu publicar com ajuda guiada. Abaixo está o roteiro completo. Como o **Git não
> está instalado** nesta máquina, a forma mais simples é o **GitHub Desktop** (opção A). Se
> preferir linha de comando, use a opção B.

### Pré-requisito
- Uma conta no **GitHub** (gratuita): <https://github.com/signup>.

### Opção A — GitHub Desktop (recomendada, sem terminal)
1. Instale o **GitHub Desktop**: <https://desktop.github.com> e faça login na sua conta.
2. Menu **File → Add local repository…** e selecione esta pasta
   (`Projeto DashBoard AgroEnergia`). Ele vai oferecer **"create a repository"** — aceite
   (deixe o nome, por ex. `painel-agro-energia`).
3. Clique em **Commit to main** (mensagem: "versão inicial").
4. Clique em **Publish repository**. **Desmarque "Keep this code private"** se quiser que o
   link funcione para qualquer pessoa (o GitHub Pages gratuito precisa de repositório
   **público**). Clique em **Publish**.
5. No navegador, abra o repositório no GitHub → **Settings → Pages**:
   - **Source:** *Deploy from a branch*
   - **Branch:** `main` e pasta **`/ (root)`** → **Save**.
6. Ainda em **Settings → Actions → General → Workflow permissions**: marque
   **"Read and write permissions"** → **Save** (permite o cron commitar os dados).
7. Vá na aba **Actions**, abra **"Atualizar dados do painel"** e clique em **Run workflow**
   para a primeira coleta (depois ele roda sozinho a cada 6h).
8. Em 1–2 minutos o link público estará ativo em:
   **`https://SEU-USUARIO.github.io/painel-agro-energia/`**
   (o endereço exato aparece em **Settings → Pages**). É esse link que você compartilha.

### Opção B — Git por linha de comando
1. Instale o Git: <https://git-scm.com/download/win> e crie o repositório vazio no GitHub.
2. Nesta pasta, rode:
   ```bash
   git init
   git add .
   git commit -m "versão inicial"
   git branch -M main
   git remote add origin https://github.com/SEU-USUARIO/painel-agro-energia.git
   git push -u origin main
   ```
3. Siga os passos **5 a 8** da Opção A (Pages, permissões, Run workflow).

> **Dica:** o repositório já vem com `data/latest.json` e `data/history.json` gerados, então o
> painel já abre com dados mesmo antes do primeiro cron.

---

## 5. Como eu altero as recomendações (limiares)

Edite **`config/thresholds.json`**. Cada regra dispara quando **todas** as condições em
`quando` são verdadeiras, e o painel mostra o indicador e o limiar que a acionaram.

```json
{
  "id": "selic_queda_capex",
  "titulo": "Janela melhor para financiar expansão/CAPEX",
  "mensagem": "A Selic está em tendência de queda...",
  "categoria": "Crédito e juros",
  "severidade": "positivo",
  "quando": [
    { "indicador": "selic", "campo": "changes.month", "operador": "<", "limiar": 0 }
  ]
}
```

- **`indicador`**: chave existente — `selic, cdi, ipca, usd, eur, soja, milho, cafe, acucar,
  algodao, boi_gordo, pld, solar`.
- **`campo`**: `value` (valor atual) ou `changes.day` / `changes.month` / `changes.year`
  (variação).
- **`operador`**: `<`, `<=`, `>`, `>=`, `==`, `!=`.
- **`limiar`**: o número de corte.
- **`severidade`**: `positivo` (verde) ou `alerta` (amarelo).
- Para combinar condições (E lógico), adicione mais objetos na lista `quando`
  (ex.: "soja subindo **e** dólar subindo").

Salvou e deu push? Na próxima vez que a página carregar, as regras novas já valem (a avaliação
é feita no navegador, lendo este arquivo).

---

## 6. PLD / energia: como manter atualizado

Por padrão o PLD vem de `config/settings.json`:

```json
"manual_overrides": {
  "pld": { "value": 150.0, "as_of": "2026-11-01", "note": "Valor configurado manualmente..." }
}
```

- **Atualizar na mão:** mude `value` e `as_of` (consulte o PLD atual no site da CCEE/ONS) e dê
  push. O card mostra o selo "manual".
- **Automatizar no futuro:** implemente a busca em `fetch_pld()` (em `collector/collect.py`),
  retornando uma lista `[{"date": "...", "value": ...}]`. Enquanto a função lançar erro, o
  painel usa o valor manual acima — então é seguro experimentar.

---

## 7. Como adiciono/removo um indicador ou um feed

### Indicador
Abra `collector/collect.py` e edite a lista **`REGISTRY`**. Para adicionar, inclua um item:

```python
{"key": "novo", "label": "Meu indicador", "unit": "R$", "group": "macro",
 "change_type": "pct", "source": "Minha Fonte", "source_url": "https://...",
 "fetch": lambda s, c: minha_funcao(s, c)}
```

- Crie a função `minha_funcao(session, cfg)` retornando `[{"date": "AAAA-MM-DD", "value": n}, ...]`
  (ordem crescente). Use as funções existentes (`get_json`, `get_text`) como exemplo.
- `change_type`: `"pct"` para preços (variação em %) ou `"pp"` para taxas (variação em pontos).
- `group`: `macro`, `cambio`, `commodities` ou `energia` (ou adicione um grupo em `GROUPS`).
- Para **remover**, apague o item do `REGISTRY`.
- O site se adapta sozinho — ele desenha o que estiver em `data/latest.json`.

### Feed de notícias
Edite `config/feeds.json` e adicione/remova itens da lista `feeds` (cada um com `name`,
`categoria` e `url` de um RSS). Dica: use o **Google News RSS** trocando o termo de busca.

---

## 8. Rodar e testar localmente

Requer Python 3.10+ (nesta máquina use `py`).

```bash
py -m pip install -r collector/requirements.txt
py collector/collect.py
py -m http.server 8000
```

Depois abra <http://localhost:8000>. (É preciso servir por HTTP — abrir o `index.html` direto
pelo arquivo não funciona, porque o navegador bloqueia a leitura dos JSON.)

---

## 9. Observações de privacidade e segurança
- O site é **estático** e só consome dados públicos — **nenhuma chave ou segredo** é usada.
- O `User-Agent` do coletor é genérico, sem dados pessoais.
- Para o cron conseguir commitar, o repositório usa o `GITHUB_TOKEN` padrão do próprio Actions
  (configurado em *Workflow permissions*); você não precisa criar nenhum token manual.
