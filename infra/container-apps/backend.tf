# Remote backend using Azure Storage Account for tfstate.
# Uncomment and fill in the values before running `terraform init`.
#
# Prerequisites:
#   az group create -n rg-tfstate -l eastus
#   az storage account create -n stbbmetricstfstate -g rg-tfstate -l eastus --sku Standard_LRS
#   az storage container create -n tfstate --account-name stbbmetricstfstate
#
terraform {
  backend "azurerm" {
    resource_group_name  = "rg-bbmetric-config"
    storage_account_name = "bbmetricscontainer"
    container_name       = "tfstate"
    key                  = "container-apps/terraform.tfstate"
  }
}
