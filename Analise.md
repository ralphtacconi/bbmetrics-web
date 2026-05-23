# Proposta de Sistema de Métricas (base Bitbucket Data Center) — foco em Qualidade

## Objetivo
Criar um sistema de métricas a partir dos dados do Bitbucket Data Center (Pull Requests, reviews/approvals, comentários e diffs) para gerar **indicadores de qualidade** (prioridade) e **velocidade de entrega** (secundário), com visões por **usuário**, **repositório** e **time**.

> Observação: Sem Jira e sem deploy no momento, o foco é em métricas “market standard” de **code review**, **risco de mudança** e **fluxo de PR**. Integrações futuras (Jira/Build/Deploy/Incidentes) podem completar DORA.

---

## Fontes de dados (Bitbucket DC)
Principais endpoints (leitura/GET):
- Listar repos do projeto  
  `GET /rest/api/1.0/projects/{projectKey}/repos`
- Listar PRs por estado (OPEN, MERGED, DECLINED)  
  `GET /rest/api/1.0/projects/{projectKey}/repos/{repoSlug}/pull-requests?state=...`
- Obter atividades do PR (inclui comentários e eventos de review)  
  `GET /rest/api/1.0/projects/{projectKey}/repos/{repoSlug}/pull-requests/{prId}/activities`
- Listar commits do PR  
  `GET /rest/api/1.0/projects/{projectKey}/repos/{repoSlug}/pull-requests/{prId}/commits`
- Diffstat do commit (linhas/arquivos alterados)  
  `GET /rest/api/1.0/projects/{projectKey}/repos/{repoSlug}/commits/{commitId}/diffstat`

---

## Métricas recomendadas (comuns no mercado)

### 1) Qualidade via Code Review (prioridade)
Métricas usadas em empresas grandes para avaliar a **saúde do processo de revisão** (proxy de qualidade).

**1.1 Review Coverage (cobertura de revisão)**
- **Approvers únicos por PR**: quantidade de usuários que aprovaram.
- **% PRs com 2+ approvers** (quando aplicável).
- **% PRs com comentário + approval**: mede se a revisão teve interação (não apenas “approve e merge”).

**Por que importa:** aumenta chance de detectar defeitos antes do merge e reduz risco de mudanças grandes sem validação.

---

**1.2 Review Responsiveness (responsividade do review)**
- **Time to First Review (TTFR)**: tempo entre criação do PR e o primeiro evento de review (comentário/review).
- **Time to First Approval**: tempo entre criação do PR e o primeiro approval.
- **Time from last commit to approval**: se o PR muda muito, mede se a aprovação foi “em cima do estado final”.

**Por que importa:** review rápido reduz retrabalho, diminui risco e evita PRs envelhecidos.

---

**1.3 Review Depth (profundidade do review)**
- **Comentários totais por PR**
- **Inline comments / total comments** (proporção)
- **Comentários por 100 linhas alteradas** (normaliza por tamanho)

**Por que importa:** ajuda a identificar revisão superficial vs. revisão detalhada (sem virar “ranking”).

---

**1.4 Rework after Review (retrabalho após review)**
- **Commits after first review**: quantos commits entraram depois do primeiro review/comentário.
- (Evolução futura) **Churn after first review**: linhas alteradas após o review iniciar.

**Por que importa:** muito retrabalho pode indicar PR grande, requisitos instáveis, review tardio ou falta de alinhamento.

---

### 2) Risco de Mudança (Change Risk)
Métricas de “risco” são comuns para priorizar atenção em PRs (e ajustar políticas: mais reviewers, testes, validações).

**2.1 PR Size**
- **Files changed**, **additions**, **deletions**, **churn (add+del)**

**2.2 PR Age**
- Tempo aberto do PR (PRs muito antigos tendem a ser mais difíceis/arriscados para merge)

**2.3 Approval strength**
- Quantidade de approvers e participação de reviewers

**2.4 Risk Score (heurístico) — proposta**
Criar um score simples para uso interno, por exemplo:
- +2 se `churn > 500`
- +2 se `files_changed > 20`
- +1 se `PR age > 7 dias`
- -1 se `approvers >= 2`

**Por que importa:** gera uma lista “Top PRs de maior risco” para foco de atenção e governança.

---

### 3) Fluxo / Velocidade (secundário, mas útil)
Métricas de fluxo ajudam a reduzir fila e melhorar previsibilidade.

**3.1 PR Cycle Time**
- Tempo entre criação e merge (`created -> merged`), com p50/p75/p90 por repo/time.

**3.2 Throughput**
- PRs mergeados por semana (por repo/time).

**3.3 Aging PRs / WIP**
- PRs abertos por mais de X dias.
- PRs abertos por autor/time (cuidado para não virar “cobrança”, e sim diagnóstico).

---

## Visões (dashboards) sugeridas
### Por Repositório
- PR cycle time (p50/p90)
- Distribuição de tamanho (churn/files) e top PRs grandes
- TTFR e time to first approval
- Approval coverage (1 reviewer vs 2+)
- Aging PRs

### Por Time (sem Jira)
- Mapear `repo -> time` em um arquivo local (ex.: `teams.yml`/`teams.json`) para agregar.
- Mesmas métricas do “por repo”, agregadas por time.

### Por Usuário (com cautela)
- TTFR “recebido” (tempo até alguém revisar os PRs do autor)
- Tempo médio para aprovar/revisar PRs de outros (participação como reviewer)
- Volume de PRs mergeados (tendência, não ranking)
- Observação: evitar KPI do tipo “linhas por dev” como métrica de performance.

---

## Saídas (artefatos) sugeridas
### MVP (rápido e útil)
1) `prs.csv` (enriquecido)
- `pr_id, repo_slug, author, state`
- `created_on, merged_on/closed_on, cycle_time`
- `ttfr, time_to_first_approval`
- `approvers_count, commenters_count, comments_total, inline_comments`
- `files_changed, additions, deletions, churn`
- `risk_score`

2) `reviews_events.csv` (novo)
- 1 linha por evento (comment / inline comment / approval / unapproval / etc.)
- campos: `pr_id, repo, user, event_type, created_at, is_inline, text (opcional)`

3) `scan.log`
- log detalhado do processamento, útil para auditoria e troubleshooting.

### Evolução (futuro)
- Integração com Jira (lead time completo por issue, status/bug/feature)
- Integração com build (TeamCity) e, futuramente, deploy/incidentes (para DORA completo)

---

## Governança e boas práticas (para evitar “gaming”)
- Métricas por usuário devem ser usadas como **diagnóstico e melhoria de processo**, não como ranking.
- Preferir dashboards por **time/repo** como visão principal.
- Usar percentis (p50/p90) e tendências semanais ao invés de médias simples.

---

## Próximos passos sugeridos
1) Confirmar onde os approvals aparecem no Bitbucket DC:
   - como status do reviewer no PR e/ou como evento em `/activities`.
2) Definir arquivo de mapeamento `repo -> time` (se desejado).
3) Implementar coleta de:
   - eventos de approval
   - timestamps para TTFR/time_to_first_approval
   - agregação diffstat por PR
4) Publicar as saídas em CSV (ou JSON) e montar dashboard (Excel/PowerBI/Grafana).

---
Fim.