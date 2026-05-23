#!/bin/bash
set -euo pipefail

bash argocd/install/install-argocd.sh
kubectl apply -f argocd/application.yaml
