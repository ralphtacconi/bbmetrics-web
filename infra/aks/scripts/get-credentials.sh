#!/bin/bash
set -euo pipefail

RESOURCE_GROUP=${1:-bbmetrics-aks-rg}
CLUSTER_NAME=${2:-bbmetrics-aks}

az aks get-credentials --resource-group "$RESOURCE_GROUP" --name "$CLUSTER_NAME" --overwrite-existing
