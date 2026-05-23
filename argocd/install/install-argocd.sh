#!/bin/bash
set -euo pipefail

# Install ArgoCD in the AKS cluster
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
# Wait for pods to become ready
kubectl wait --for=condition=available --timeout=300s deployment/argocd-server -n argocd
# Get initial password
echo "ArgoCD initial password:"
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
echo ""
# Port-forward for local access
echo "Run: kubectl port-forward svc/argocd-server -n argocd 8080:443"
