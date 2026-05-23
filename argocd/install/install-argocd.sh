#!/bin/bash
set -euo pipefail

# Instala ArgoCD no cluster AKS
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
# Aguarda pods ficarem ready
kubectl wait --for=condition=available --timeout=300s deployment/argocd-server -n argocd
# Obtém senha inicial
echo "ArgoCD initial password:"
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
echo ""
# Port-forward para acesso local
echo "Run: kubectl port-forward svc/argocd-server -n argocd 8080:443"
