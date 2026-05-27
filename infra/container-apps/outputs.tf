output "container_app_url" {
  description = "BBMetrics web application URL"
  value       = "https://${azurerm_container_app.bbmetrics.latest_revision_fqdn}"
}

output "acr_login_server" {
  description = "Azure Container Registry login server"
  value       = var.acr_login_server
}

output "cosmos_endpoint" {
  description = "Cosmos DB endpoint"
  value       = azurerm_cosmosdb_account.bbmetrics.endpoint
}

output "app_insights_connection_string" {
  description = "Application Insights connection string"
  value       = azurerm_application_insights.bbmetrics.connection_string
  sensitive   = true
}
