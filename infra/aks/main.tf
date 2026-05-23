terraform {
  required_version = ">= 1.5.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.110"
    }
  }
}

provider "azurerm" {
  features {}
}

resource "azurerm_resource_group" "bbmetrics" {
  name     = var.resource_group_name
  location = var.location
}

resource "azurerm_log_analytics_workspace" "bbmetrics" {
  name                = "${var.aks_cluster_name}-law"
  location            = azurerm_resource_group.bbmetrics.location
  resource_group_name = azurerm_resource_group.bbmetrics.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

resource "azurerm_application_insights" "bbmetrics" {
  name                = "${var.aks_cluster_name}-appi"
  location            = azurerm_resource_group.bbmetrics.location
  resource_group_name = azurerm_resource_group.bbmetrics.name
  application_type    = "web"
  workspace_id        = azurerm_log_analytics_workspace.bbmetrics.id
}

resource "azurerm_container_registry" "bbmetrics" {
  name                = replace("${var.aks_cluster_name}acr", "-", "")
  resource_group_name = azurerm_resource_group.bbmetrics.name
  location            = azurerm_resource_group.bbmetrics.location
  sku                 = "Basic"
  admin_enabled       = false
}

resource "azurerm_cosmosdb_account" "bbmetrics" {
  name                = "${var.aks_cluster_name}-cosmos"
  location            = azurerm_resource_group.bbmetrics.location
  resource_group_name = azurerm_resource_group.bbmetrics.name
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"
  enable_free_tier    = true
  consistency_policy {
    consistency_level = "Session"
  }
  geo_location {
    location          = azurerm_resource_group.bbmetrics.location
    failover_priority = 0
  }
}

resource "azurerm_cosmosdb_sql_database" "bbmetrics" {
  name                = "bbmetrics"
  resource_group_name = azurerm_resource_group.bbmetrics.name
  account_name        = azurerm_cosmosdb_account.bbmetrics.name
}

resource "azurerm_cosmosdb_sql_container" "scans" {
  name                  = "scans"
  resource_group_name   = azurerm_resource_group.bbmetrics.name
  account_name          = azurerm_cosmosdb_account.bbmetrics.name
  database_name         = azurerm_cosmosdb_sql_database.bbmetrics.name
  partition_key_path    = "/scan_id"
  partition_key_version = 1
}

resource "azurerm_key_vault" "bbmetrics" {
  name                        = "${var.aks_cluster_name}-kv"
  location                    = azurerm_resource_group.bbmetrics.location
  resource_group_name         = azurerm_resource_group.bbmetrics.name
  tenant_id                   = data.azurerm_client_config.current.tenant_id
  sku_name                    = "standard"
  purge_protection_enabled    = false
  soft_delete_retention_days  = 7
}

data "azurerm_client_config" "current" {}

resource "azurerm_kubernetes_cluster" "bbmetrics" {
  name                = var.aks_cluster_name
  location            = azurerm_resource_group.bbmetrics.location
  resource_group_name = azurerm_resource_group.bbmetrics.name
  dns_prefix          = var.aks_cluster_name

  default_node_pool {
    name       = "default"
    node_count = var.node_count
    vm_size    = var.vm_size
  }

  identity {
    type = "SystemAssigned"
  }

  oms_agent {
    log_analytics_workspace_id = azurerm_log_analytics_workspace.bbmetrics.id
  }
}

resource "azurerm_role_assignment" "aks_acr_pull" {
  scope                = azurerm_container_registry.bbmetrics.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_kubernetes_cluster.bbmetrics.kubelet_identity[0].object_id
}

resource "azurerm_role_assignment" "aks_metrics_publisher" {
  scope                = azurerm_resource_group.bbmetrics.id
  role_definition_name = "Monitoring Metrics Publisher"
  principal_id         = azurerm_kubernetes_cluster.bbmetrics.identity[0].principal_id
}
