variable "location" {
  type    = string
  default = "eastus"
}

variable "resource_group_name" {
  type    = string
  default = "bbmetrics-aks-rg"
}

variable "aks_cluster_name" {
  type    = string
  default = "bbmetrics-aks"
}

variable "node_count" {
  type    = number
  default = 2
}

variable "vm_size" {
  type    = string
  default = "Standard_B2s"
}
