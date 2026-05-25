# BBMetrics Web

Aplicação web para coleta e análise de métricas de Pull Requests no Bitbucket Data Center, hospedada no Azure.

## Arquitetura

```
┌──────────────────────────────────────────────────────────────────┐
│                         Azure                                     │
│                                                                   │
│  ┌─────────────────┐    ┌──────────────────┐  ┌───────────────┐ │
│  │ Container Apps  │───▶│   Cosmos DB      │  │  Key Vault    │ │
│  │  (FastAPI/Uvic) │    │  (scans docs)    │  │  (secrets)    │ │
│  └────────┬────────┘    └──────────────────┘  └───────────────┘ │
│           │                                                       │
│  ┌────────▼────────┐    ┌──────────────────┐                    │
│  │      ACR        │    │  App Insights    │                    │
│  │  (Docker images)│    │  (observability) │                    │
│  └─────────────────┘    └──────────────────┘                    │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │           Azure OpenAI (GPT-4o) — AI Insights (opcional)    │ │
│  └─────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘

GitHub Actions CI/CD:
  push → lint + test → docker build → ACR push → Container Apps deploy
```

### Stack

| Camada | Tecnologia |
|--------|-----------|
| Backend | FastAPI + Uvicorn |
| Templates | Jinja2 + Tailwind CSS (dark theme) |
| Banco de dados | Azure Cosmos DB (NoSQL) |
| Container | Docker (single container) |
| Registry | Azure Container Registry |
| Hosting | Azure Container Apps |
| Secrets | Azure Key Vault |
| Observabilidade | Azure Application Insights |
| IA | Azure OpenAI GPT-4o (opcional) |
| IaC | Terraform |
| CI/CD | GitHub Actions |

---

## Rodando Localmente

### Pré-requisitos

- Docker e Docker Compose
- Python 3.11+ (para desenvolvimento sem Docker)
- Acesso ao Bitbucket Data Center

### Com Docker Compose

```bash
# 1. Copiar e preencher variáveis de ambiente
cp .env.example .env
# Editar .env com suas credenciais

# 2. Iniciar a aplicação
docker compose up --build

# 3. Acessar em http://localhost:8000
```

### Sem Docker (desenvolvimento)

```bash
# 1. Criar ambiente virtual
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# 2. Instalar dependências
pip install -r requirements.txt

# 3. Configurar variáveis de ambiente
cp .env.example .env
# Editar .env

# 4. Iniciar o servidor
uvicorn app.main:app --reload --port 8000
```

---

## Deploy no Azure com Terraform

### Pré-requisitos

- [Azure CLI](https://docs.microsoft.com/cli/azure/install-azure-cli) instalado e autenticado (`az login`)
- [Terraform](https://developer.hashicorp.com/terraform/install) >= 1.5

### Passos

```bash
cd infra/container-apps

# 1. Copiar e ajustar variáveis
cp terraform.tfvars terraform.tfvars
# Editar terraform.tfvars com nomes únicos para ACR e Cosmos DB

# 2. (Opcional) Configurar backend remoto em backend.tf
# Siga as instruções comentadas no arquivo

# 3. Inicializar Terraform
terraform init

# 4. Visualizar plano
terraform plan

# 5. Aplicar infraestrutura
terraform apply

# 6. Obter URL da aplicação
terraform output container_app_url
```

### Destruir infraestrutura

```bash
terraform destroy
```

> ⚠️ Use `terraform destroy` para evitar cobranças quando não estiver usando.

---

## Configuração do CI/CD

### GitHub Actions

Configure as seguintes **secrets** e **variables** no repositório:

**Secrets** (Settings → Secrets → Actions):
| Secret | Descrição |
|--------|-----------|
| `AZURE_CLIENT_ID` | Client ID do Service Principal com OIDC |
| `AZURE_TENANT_ID` | Tenant ID do Azure AD |
| `AZURE_SUBSCRIPTION_ID` | Subscription ID do Azure |

**Variables** (Settings → Variables → Actions):
| Variable | Exemplo |
|----------|---------|
| `ACR_NAME` | `acrbbmetricsdev` |
| `CONTAINER_APP_NAME` | `bbmetrics` |
| `RESOURCE_GROUP` | `rg-bbmetrics` |

### Configurar OIDC com Azure

```bash
# Criar App Registration e federated credential para GitHub Actions
az ad app create --display-name bbmetrics-github-actions
APP_ID=$(az ad app list --display-name bbmetrics-github-actions --query "[0].appId" -o tsv)

az ad sp create --id $APP_ID
SP_OBJECT_ID=$(az ad sp show --id $APP_ID --query id -o tsv)

# Atribuir permissões na subscription
az role assignment create \
  --role Contributor \
  --assignee-object-id $SP_OBJECT_ID \
  --scope /subscriptions/YOUR_SUBSCRIPTION_ID

# Adicionar federated credential (ajustar org/repo)
az ad app federated-credential create \
  --id $APP_ID \
  --parameters '{
    "name": "github-actions",
    "issuer": "https://token.actions.githubusercontent.com",
    "subject": "repo:ralphtacconi/bbmetrics-web:ref:refs/heads/master",
    "audiences": ["api://AzureADTokenExchange"]
  }'
```

---

## Azure OpenAI (Opcional)

Para habilitar os insights de IA em código de revisão, configure no `.env`:

```env
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_KEY=your-api-key
AZURE_OPENAI_DEPLOYMENT=gpt-4o
```

Se não configurado, a aplicação funciona normalmente sem insights de IA (graceful degradation).

---

## Estimativa de Custos (East US)

| Serviço | SKU | Estimativa/mês |
|---------|-----|---------------|
| Azure Container Apps | Min 0 réplicas | ~$0–15 |
| Azure Cosmos DB | Free tier (1000 RU/s + 25GB) | **$0** |
| Azure Container Registry | Basic | ~$5 |
| Azure Key Vault | Standard | ~$1 |
| Azure Application Insights | Pay-per-use | ~$5–10 |
| Azure OpenAI | GPT-4o (opcional) | ~$5–20 |
| **Total estimado** | | **~$16–51/mês** ✅ |

> 💡 Cosmos DB free tier: apenas **uma conta por subscription**. Inclui 1000 RU/s e 25GB gratuitamente.

---

## Estrutura do Projeto

```
bbmetrics-web/
├── app/                    # FastAPI web application
│   ├── main.py             # Routes, endpoints, background tasks
│   ├── cosmos.py           # Azure Cosmos DB client
│   ├── ai_insights.py      # Azure OpenAI integration
│   ├── templates/          # Jinja2 templates (dark theme)
│   │   ├── base.html
│   │   ├── index.html      # Dashboard
│   │   ├── scan.html       # New scan form
│   │   ├── results.html    # Scan results + charts
│   │   └── _scan_status.html
│   └── static/
│       └── app.js          # Frontend JS (polling, charts)
├── bbmetrics_dc/           # Core business logic (unchanged)
│   ├── client.py
│   ├── cli.py
│   ├── collect_prs.py
│   ├── collect_repos.py
│   ├── metrics.py
│   └── ...
├── BBMetrics_UI/           # Legacy Qt UI (kept for reference)
├── infra/
│   └── container-apps/     # Terraform: Azure Container Apps
│       ├── main.tf
│       ├── variables.tf
│       ├── outputs.tf
│       ├── backend.tf
│       └── terraform.tfvars.example
├── .github/workflows/
│   ├── ci.yml              # Lint + test
│   └── cd.yml              # Build + deploy to Azure
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── requirements.txt
```
