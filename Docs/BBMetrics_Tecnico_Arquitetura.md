# BBMetrics — Documento Técnico (Arquitetura / Implementação)

## Visão geral
A solução é composta por 2 partes principais:

1) **BBMetrics_UI** (GUI em PySide6)  
- Interface para selecionar parâmetros (credenciais, project, repos, users/groups, datas, estados)  
- Executa o scan chamando o módulo `bbmetrics_dc.cli.scan()` e captura stdout para exibir log + progresso.

2) **bbmetrics_dc** (core/collector em Python)  
- Cliente HTTP para Bitbucket Data Center  
- Funções para listar PRs, buscar activities e calcular métricas  
- Exporta os resultados em CSV para a pasta de saída.

---

## Estrutura de alto nível (módulos)
### `BBMetrics_UI/app.py`
- Constrói a UI (Qt Widgets)
- Workers (QThread) para não travar a interface:
  - `ProjectsWorker`: carrega projects via API
  - `ReposWorker`: carrega repos do project via API
  - `CliWorker`: executa scan (python) e captura stdout
- Captura linhas impressas pelo backend via `_LineEmitter` + `redirect_stdout`
- Interpreta “markers” no stdout para progresso/stage:
  - `__BBMETRICS_STAGE__ <texto>`
  - `__BBMETRICS_PROGRESS__ <current> <total>`
- Lê CSVs (summary) e gera gráficos/tabela (QtCharts), se disponível.

### `BBMetrics_UI/bb_api.py`
- Camada “API” consumida pela UI:
  - `list_projects(client)`
  - `list_repos_in_project(client, project_key)`
- Normalmente usa `bbmetrics_dc.client.BitbucketDCClient` para chamadas HTTP.

### `bbmetrics_dc/client.py`
- Cliente para Bitbucket Data Center:
  - autenticação (basic/token)
  - método `paginate(endpoint, params=...)` para percorrer páginas dos endpoints (start/limit ou similar).
- Centraliza requests e tratamento de paginação.

### `bbmetrics_dc/collect_prs.py`
- Listagem e coleta ligada a PRs:
  - `list_pull_requests(...)`: varre PRs de um repo e state (`OPEN/MERGED/DECLINED`)
    - suporta early-stop *somente* quando consegue confirmar ordenação DESC (newest-first)
    - caso contrário faz scan até `max_prs_scanned`
  - `list_pr_activities(...)`: pagina activities por PR
  - `extract_review_events(...)`: normaliza activities para “ReviewEvent”
  - `compute_review_metrics_from_events(...)`: calcula métricas (first review, first approval, comments, time open etc.)
  - `estimate_time_open_minutes(...)`: calcula tempo aberto baseado em created/closed/updated

### `bbmetrics_dc/cli.py`
- Orquestra o scan:
  - valida parâmetros (datas, repos, project)
  - resolve filtros de user/group (author)
  - lista repos (via `collect_repos.py`)
  - lista PRs e filtra por intervalo de data
  - busca activities (com limite) para calcular métricas
  - exporta CSVs (`export_csv.write_csv`)
  - emite markers de stage/progresso para UI

### `bbmetrics_dc/collect_repos.py`
- Funções para listar repositórios de um project no Bitbucket DC.

### `bbmetrics_dc/export_csv.py`
- Rotinas de escrita de CSV (headers + rows).

### `bbmetrics_dc/metrics.py`
- Consolida “rows” em resumos por usuário e por grupo:
  - médias por repo/usuário/grupo
  - contagens etc.

### `bbmetrics_dc/timeutil.py`
- Utilitários:
  - `from_epoch_ms(ms)`
  - `utc_now()`

---

## Principais bibliotecas (dependências)
### UI
- `PySide6`:
  - `QtWidgets` para interface
  - `QtCore` para threads/signals
  - `QtGui` para palette/ícones
- `PySide6.QtCharts` (opcional):
  - habilita gráficos (se não estiver no build, charts são desativados)

### Core
- `typer`:
  - CLI e parsing de opções (comando `scan`)
- Biblioteca HTTP (depende de como `BitbucketDCClient` foi implementado; comum: `requests`):
  - autenticação
  - chamadas REST
- `csv`, `datetime`, `pathlib`, `typing` (stdlib)

---

## APIs do Bitbucket DC chamadas (principais)
> Endpoints típicos (Bitbucket Data Center, REST v1.0). Os paths abaixo são consistentes com o que aparece no código.

### Listar PRs por repo/state
- `GET /rest/api/1.0/projects/{projectKey}/repos/{repoSlug}/pull-requests`
- params típicos:
  - `state=OPEN|MERGED|DECLINED`
  - `limit=<N>`
  - paginação via `start` (gerenciado em `client.paginate`)

### Listar activities de um PR
- `GET /rest/api/1.0/projects/{projectKey}/repos/{repoSlug}/pull-requests/{prId}/activities`
- params:
  - `limit=100` (por página)

### Listar projects / repos
(depende da implementação em `BBMetrics_UI.bb_api` / `collect_repos`, normalmente algo como:)
- `GET /rest/api/1.0/projects`
- `GET /rest/api/1.0/projects/{projectKey}/repos`

---

## Como o filtro de datas funciona (ponto crítico)
O Bitbucket DC não oferece filtro direto por createdDate/closedDate no endpoint de PRs; então o app:
1) lista PRs (por state) via paginação
2) filtra “na mão” com base em timestamps do PR:
   - `createdDate` (epoch ms)
   - `closedDate` (epoch ms, pode ser None)
   - `updatedDate` fallback quando `closedDate` não existe

### Comportamento atual (recomendado)
- Quando o usuário escolhe **MERGED only**:
  - a UI passa `date_field="closed"`
  - o core filtra por `closedDate` (ou `updatedDate` fallback) dentro do range
- Quando escolhe **ALL states**:
  - a UI passa `date_field="created"`
  - o core filtra por `createdDate`

Isso evita o caso clássico de “não trouxe nada” quando o usuário quer “mergeados no período”.

---

## Como o progresso funciona
O backend emite no stdout:

- `__BBMETRICS_STAGE__ <texto>`: fase atual (Loading repos, Listing PRs, Processing PRs, Writing…)
- `__BBMETRICS_PROGRESS__ <current> <total>`: progresso quantitativo da fase de processamento de PRs

A UI:
- captura stdout via `_LineEmitter` e `redirect_stdout`
- quando detecta os markers:
  - atualiza label de status
  - atualiza progress bar
- linhas normais vão para o log.

---

## Observações de performance / trade-offs
1) **Limite de activities (`activities_limit`)**
- Ler todas as activities de PRs grandes pode ser caro.
- O app permite limitar (25/50/100/200/ALL).
- Em modo “Summaries”, dá para parar cedo (stop_when_ready) após achar primeiros eventos úteis (review/approval).

2) **Ordenação de listagem de PRs**
- O endpoint pode retornar em ordem não garantida; por isso o `list_pull_requests` tenta detectar ASC/DESC para early-stop com segurança.
- Quando não é possível confirmar DESC, usa um `max_prs_scanned` para evitar varrer histórico infinito.

---

## Onde alterar / estender
### Adicionar novos campos nos CSVs
- `bbmetrics_dc/cli.py`:
  - montar colunas extras em `pr_rows`, `review_event_rows`, `pr_review_metrics_rows`
- `export_csv.write_csv` escreve dinamicamente com base nas chaves do dict.

### Adicionar novo filtro (ex.: por reviewer em vez de author)
- Exige varrer activities para identificar reviewers/approvers e filtrar PRs por isso (mais caro).
- Implementação provável em `cli.py` (fase de listagem) chamando activities antes de decidir incluir o PR.

### Adicionar novos gráficos
- `BBMetrics_UI/app.py` na classe `ChartsTab`:
  - ler CSVs e montar novas séries/tabela

---

## Como rodar (dev)
- UI: executar `python -m BBMetrics_UI.app` (dependendo do layout do projeto)
- CLI: `python -m bbmetrics_dc.cli scan --project-key ...`

(ajuste conforme seu entrypoint real)

---