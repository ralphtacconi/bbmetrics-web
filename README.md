# BBMetrics Web (AKS + ArgoCD)

Aplicação web moderna para coleta de métricas de PR/review no Bitbucket, mantendo a lógica de negócio do módulo `bbmetrics_dc/`.

## Arquitetura

```text
Users -> NGINX Ingress -> FastAPI (AKS)
                         -> Cosmos DB (scans/results)
                         -> Azure OpenAI (AI Insights)
                         -> Application Insights / Azure Monitor

Git push -> GitHub Actions (build/push image + update kustomization)
         -> ArgoCD (detecta mudança Git e sincroniza no AKS)
```

## Stack
- Backend: FastAPI + Uvicorn
- Frontend: Jinja2 + Tailwind CDN + Chart.js
- Persistência: Azure Cosmos DB
- Infra: AKS, ACR, Key Vault, App Insights (Terraform)
- GitOps: ArgoCD

## Fluxo GitOps
1. Developer faz push de código
2. GitHub Actions CI executa validações
3. GitHub Actions CD builda e publica imagem no ACR com tag `sha-<7>`
4. Workflow atualiza `k8s/overlays/production/kustomization.yaml`
5. ArgoCD detecta a mudança e faz sync automático no AKS

## Execução local
```bash
cp .env.example .env
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Provisionar AKS
```bash
cd infra/aks
terraform init
terraform apply
```

## Economizar custos (destruir cluster)
```bash
cd infra/aks
terraform destroy -target=azurerm_kubernetes_cluster.bbmetrics
```
Ou use o workflow manual `Terraform Destroy AKS`.

## ArgoCD
```bash
bash argocd/install/install-argocd.sh
kubectl apply -f argocd/application.yaml
```

## Custos estimados
- AKS (2x Standard_B2s) + observabilidade + ACR + Cosmos free tier: ~US$100–135/mês
- Estratégia recomendada: destruir AKS fora do horário de uso para ficar dentro do orçamento.
