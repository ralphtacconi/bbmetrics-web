# ArgoCD on AKS

## Instalação
```bash
bash argocd/install/install-argocd.sh
```

## Registrar aplicação GitOps
```bash
kubectl apply -f argocd/application.yaml
```

## Verificar
```bash
kubectl get applications -n argocd
kubectl get pods -n bbmetrics
```
