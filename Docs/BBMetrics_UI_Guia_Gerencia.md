# BBMetrics UI — Guia (Gerência / Usuários)

## Objetivo do aplicativo
O **BBMetrics UI** coleta dados de Pull Requests (PRs) no Bitbucket Data Center e gera **CSVs** com métricas de PR por repositório e por usuário/grupo (ex.: tempo médio de PR aberta, tempo até primeira revisão, tempo até primeira aprovação etc.).  
Ele foi feito para **acelerar a coleta**, padronizar a análise e permitir comparar repos/usuários no mesmo período.

---

## Fluxo geral (em alto nível)
1. Você informa credenciais e conecta no Bitbucket.
2. Carrega Projects e Repos.
3. Seleciona o Project, os Repos e os filtros (usuários/grupos, datas, estados, limite de activities).
4. Clica em **Run**.
5. O app gera arquivos `.csv` em uma pasta de saída (**Output dir**).
6. (Opcional) Exibe gráficos (aba **Charts**) usando os CSVs de resumo.

---

## Seção “Credentials / Connection”
### Base URL
- Endereço do Bitbucket Data Center (ex.: `https://...:8443`).
- É usado para montar as URLs das chamadas de API.

### BITBUCKET_USERNAME
- Usuário de autenticação no Bitbucket DC.

### BITBUCKET_PASSWORD (token)
- Token/senha para autenticação.
- Em geral deve ser **token** (melhor que senha), conforme política interna.

### Load Projects/Repos
- Testa a conexão e carrega:
  - lista de **Projects**
  - lista de **Repos** do Project selecionado

---

## Seção “Selection”
### Project
- Seleção do projeto Bitbucket (ex.: `KIOSK`).

### Repos (multi)
- Você seleciona **um ou mais repositórios** para incluir no scan.
- “multi” = pode marcar vários ao mesmo tempo.

---

## Seção “Filters”
### User/Group (PR author)
- **O filtro é pelo AUTHOR do PR** (quem abriu o PR), não por reviewer/aprovador.
- Se você escolher “user”, você filtra por logins individuais.
- Se você escolher “group”, você filtra pelos grupos definidos no `users.csv` (mapeamento grupo → users).

#### Mode: user | group
- **user**: lista mostra usuários
- **group**: lista mostra grupos; o app expande para os usuários do grupo ao rodar.

#### Source: users.csv
- Mostra qual arquivo `users.csv` está sendo usado.
- Esse CSV precisa ter colunas: `user,group`.

#### Search (contains) + Select all + Clear
- Ajuda a achar/selecionar rápido os autores que vão entrar no scan.

### PR Start / PR End (MM-DD-YYYY)
- Define o intervalo de datas do relatório.
- O significado exato da data depende do “PR state(s)” selecionado (ver abaixo):
  - **MERGED only**: filtra por **data de fechamento/merge** (closedDate)
  - **ALL**: filtra por **data de criação** (createdDate)

> Observação: isso foi feito para bater com o uso mais comum: quando a pessoa quer “PRs mergeados no período”, o filtro precisa ser por `closedDate`.

---

## Seção “Run / Output”
### Output dir
- Pasta onde os CSVs serão gravados.
- O log do scan (`scan.log`) também vai para essa pasta.

### Enable diffstat (SLOW)
- Quando habilitado, coleta estatísticas de diff/commits (linhas/arquivos alterados).
- Impacta performance; use apenas quando realmente precisar desses números.

### Output mode: Summaries | Full
- **Summaries**: gera os CSVs de resumo (mais rápido).
- **Full**: gera também CSVs detalhados (events/metrics/PRs), útil para auditoria e análises mais profundas.

### PR state(s)
- **MERGED only (fast)**:
  - traz apenas PRs mergeados
  - intervalo de datas é interpretado por **closedDate** (data do merge/fechamento)
  - normalmente é o modo “relatório gerencial” do que foi entregue no período
- **ALL (OPEN,MERGED,DECLINED)**:
  - inclui PRs abertos, mergeados e recusados
  - intervalo de datas é interpretado por **createdDate** (data de criação do PR)

### Activities per PR
Define quantas “activities” do PR serão lidas (comentários, approvals, opened, merged etc.).

- Valores numéricos (25/50/100/200): limita para ficar mais rápido
- **ALL**: tenta ler todas as activities (pode ficar lento em PRs com muito histórico)

> Nota: “activity” não é o “estado do PR”. Um PR mergeado sempre tem activity `OPENED`, por exemplo.

### Show charts after run
- Se marcado, ao final abre a aba **Charts** e desenha gráficos a partir dos CSVs de resumo.

### Run
- Executa o scan com os parâmetros selecionados.

### Open Output Folder
- Abre a pasta de saída no Windows Explorer.

---

## Log e Progresso
### Log
- Mostra o andamento e mensagens do scan.
- Ajuda a entender se o scan achou PRs ou se filtros zeraram resultados.

### Barra de progresso
- Durante “Listing PRs…” pode ficar em modo indeterminado (sem % exato).
- Durante “Processing PRs…”, progride baseado em “PRs processados / total encontrado”.

---

## Arquivos gerados (saída)
Os nomes podem variar um pouco conforme modo, mas normalmente:

### Sempre (ou quase sempre)
- `users_summary.csv`: resumo por usuário e repo
- `groups_summary.csv`: resumo por grupo e repo (quando modo “group”)

### No modo Full
- `prs.csv`: lista de PRs considerados no scan
- `pr_review_events.csv`: lista de eventos (activities relevantes) por PR (opened/approved/commented/merged etc.)
- `pr_review_metrics.csv`: métricas calculadas por PR (tempo aberto, time-to-first-review etc.)
- `scan.log`: log do run

---

## Dicas para evitar “não trouxe nada”
Se o log mostrar `PRs in range ...: 0`, geralmente é por:
- intervalo de datas não bate com o critério (created vs closed), ou
- filtros muito restritivos (repos/usuários).

Para relatórios de entrega (merge), use **MERGED only** e confirme datas corretas.

---