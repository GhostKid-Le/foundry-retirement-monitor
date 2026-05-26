$ErrorActionPreference = 'Stop'
Set-Location "c:\Users\lewang2\OneDrive - Microsoft\Documents\WorkSpace - VSCode\foundry-retirement-monitor"
git add -A
git status --short
git commit -m "Migrate to AKS + Application Gateway + cert-manager`n`n- Replace Flex Consumption Functions with AKS Deployment + CronJob`n- Add Bicep: AKS, AGIC addon, AppGw v2, VNet, NSG with 80/443 inbound, Network Contributor on VNet for AGIC UAMI`n- Add Dockerfile (python:3.11-slim + tzdata Asia/Shanghai)`n- Add k8s manifests (ns, PVC, secret example, web Deployment/Service, AGIC Ingress with TLS, daily-check CronJob, Let's Encrypt ClusterIssuer)`n- Add helper PowerShell scripts (deploy / probe / reconcile / cert status)`n- Remove old Functions code, ACS, azure.yaml, parameter files`n- Rewrite README for the new architecture"
git push origin main
