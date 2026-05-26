subscription_id   = "5f52642b-66f4-446b-897f-272d91e2a831"           # ID da sua Subscription no Azure
resource_group    = "rg-bbmetrics"                                   # Nome do Resource Group
location          = "brazilsouth"                                    # Região onde os recursos serão criados
container_app_env = "bbmetrics-env"                                  # Nome do ambiente do Azure Container Apps (se usado)
acr_name          = "acrbbmetricsdev"                                # Nome do Azure Container Registry (sem o domínio azurecr.io)
image_name        = "bbmetrics-web"                                  # Nome da imagem do container
image_tag         = "latest"                                         # Tag da imagem