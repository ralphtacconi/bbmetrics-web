output "kube_config" {
  value     = azurerm_kubernetes_cluster.bbmetrics.kube_config_raw
  sensitive = true
}

output "acr_login_server" {
  value = azurerm_container_registry.bbmetrics.login_server
}

output "cosmos_endpoint" {
  value = azurerm_cosmosdb_account.bbmetrics.endpoint
}

output "aks_cluster_name" {
  value = azurerm_kubernetes_cluster.bbmetrics.name
}

output "app_insights_connection_string" {
  value = azurerm_application_insights.bbmetrics.connection_string
}
