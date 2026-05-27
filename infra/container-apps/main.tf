terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.110"
    }
  }
  required_version = ">= 1.5"
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

# ─── Resource Group ─────────────────────────────────────────────────────────
resource "azurerm_resource_group" "bbmetrics" {
  name     = var.resource_group_name
  location = var.location
}

# ─── Log Analytics Workspace ─────────────────────────────────────────────────
resource "azurerm_log_analytics_workspace" "bbmetrics" {
  name                = "${var.app_name}-logs"
  location            = azurerm_resource_group.bbmetrics.location
  resource_group_name = azurerm_resource_group.bbmetrics.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

# ─── Application Insights ────────────────────────────────────────────────────
resource "azurerm_application_insights" "bbmetrics" {
  name                = "${var.app_name}-appinsights"
  location            = azurerm_resource_group.bbmetrics.location
  resource_group_name = azurerm_resource_group.bbmetrics.name
  workspace_id        = azurerm_log_analytics_workspace.bbmetrics.id
  application_type    = "web"
}

# ─── Container Registry ───────────────────────────────────────────────────────
# resource "azurerm_container_registry" "bbmetrics" {
#   name                = var.acr_name
#   location            = azurerm_resource_group.bbmetrics.location
#   resource_group_name = "rg-bbmetric-config"
#   sku                 = "Basic"
#   admin_enabled       = true
# }

# ─── Cosmos DB ───────────────────────────────────────────────────────────────
resource "azurerm_cosmosdb_account" "bbmetrics" {
  name                = var.cosmos_account_name
  location            = "Brazil South"
  resource_group_name = azurerm_resource_group.bbmetrics.name
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"

  free_tier_enabled = true

  consistency_policy {
    consistency_level = "Session"
  }

  geo_location {
    location          = "Brazil South"
    failover_priority = 0
  }
}

resource "azurerm_cosmosdb_sql_database" "bbmetrics" {
  name                = "bbmetrics"
  resource_group_name = azurerm_resource_group.bbmetrics.name
  account_name        = azurerm_cosmosdb_account.bbmetrics.name
}

resource "azurerm_cosmosdb_sql_container" "scans" {
  name                = "scans"
  resource_group_name = azurerm_resource_group.bbmetrics.name
  account_name        = azurerm_cosmosdb_account.bbmetrics.name
  database_name       = azurerm_cosmosdb_sql_database.bbmetrics.name
  partition_key_paths  = ["/scan_id"]
  throughput          = 400
}

# ─── Key Vault ───────────────────────────────────────────────────────────────
data "azurerm_client_config" "current" {}

resource "azurerm_key_vault" "bbmetrics" {
  name                = "${var.app_name}-kv"
  location            = azurerm_resource_group.bbmetrics.location
  resource_group_name = azurerm_resource_group.bbmetrics.name
  tenant_id           = data.azurerm_client_config.current.tenant_id
  sku_name            = "standard"

  access_policy {
    tenant_id = data.azurerm_client_config.current.tenant_id
    object_id = data.azurerm_client_config.current.object_id

    secret_permissions = [
      "Get", "List", "Set", "Delete", "Recover", "Backup", "Restore"
    ]
  }
}

resource "azurerm_key_vault_secret" "cosmos_connection_string" {
  name         = "cosmos-connection-string"
  value        = azurerm_cosmosdb_account.bbmetrics.primary_sql_connection_string
  key_vault_id = azurerm_key_vault.bbmetrics.id
}

resource "azurerm_key_vault_secret" "openai_api_key" {
  name         = "openai-api-key"
  value        = "REPLACE_ME"
  key_vault_id = azurerm_key_vault.bbmetrics.id

  lifecycle {
    ignore_changes = [value]
  }
}

# ─── Container App Environment ───────────────────────────────────────────────
resource "azurerm_container_app_environment" "bbmetrics" {
  name                       = "${var.app_name}-env"
  location                   = azurerm_resource_group.bbmetrics.location
  resource_group_name        = azurerm_resource_group.bbmetrics.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.bbmetrics.id
}

# ─── Container App ───────────────────────────────────────────────────────────
resource "azurerm_container_app" "bbmetrics" {
  name                         = var.app_name
  container_app_environment_id = azurerm_container_app_environment.bbmetrics.id
  resource_group_name          = azurerm_resource_group.bbmetrics.name
  revision_mode                = "Single"

  registry {
    server               = var.acr_login_server
    username             = var.acr_admin_username
    password_secret_name = "acr-password"
  }

  secret {
    name  = "acr-password"
    value = var.acr_admin_password
  }

  template {
    min_replicas = 0
    max_replicas = 3

    container {
      name   = "bbmetrics"
      image  = "${var.acr_login_server}/bbmetrics-web:latest"
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "COSMOS_ENDPOINT"
        value = azurerm_cosmosdb_account.bbmetrics.endpoint
      }

      env {
        name        = "COSMOS_KEY"
        secret_name = "cosmos-key"
      }

      env {
        name  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        value = azurerm_application_insights.bbmetrics.connection_string
      }
    }
  }

  secret {
    name  = "cosmos-key"
    value = azurerm_cosmosdb_account.bbmetrics.primary_key
  }

  ingress {
    external_enabled = true
    target_port      = 8000

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }
}
