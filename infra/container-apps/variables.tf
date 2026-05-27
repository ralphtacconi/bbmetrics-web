variable "location" {
  description = "Azure region"
  type        = string
  default     = "eastus"
}

variable "resource_group_name" {
  description = "Resource group name"
  type        = string
  default     = "rg-bbmetrics"
}

variable "acr_name" {
  description = "Azure Container Registry name (globally unique, alphanumeric)"
  type        = string
  default     = "acrbbmetrics"
}

variable "app_name" {
  description = "Container App name (used as prefix for all resources)"
  type        = string
  default     = "bbmetrics"
}

variable "cosmos_account_name" {
  description = "Cosmos DB account name (globally unique)"
  type        = string
  default     = "cosmos-bbmetrics"
}
variable "subscription_id" {
  description = "Azure Subscription ID"
  type        = string
}

variable "acr_login_server" {
  description = "login ACR"
  type = string
}
variable "acr_admin_username" {
  description = "ACR admin"
  type = string
}
variable "acr_admin_password" {
  description = "ACR pass"
}

