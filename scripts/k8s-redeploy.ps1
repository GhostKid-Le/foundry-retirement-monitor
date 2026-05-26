$ErrorActionPreference = 'Stop'
$kubectl = "C:\Users\lewang2\.azure-kubectl\kubectl.exe"
Set-Location $PSScriptRoot\..

Write-Host "==> delete old PVC + web pod"
& $kubectl -n foundry-monitor delete pvc state --ignore-not-found
& $kubectl -n foundry-monitor delete deploy web --ignore-not-found

Write-Host "==> apply new PVC + web + cronjob"
& $kubectl apply -f k8s/10-pvc.yaml
$image = "acrfoundrymonitor.azurecr.io/foundry-monitor:latest"
(Get-Content k8s/30-web.yaml -Raw) -replace '__IMAGE__', $image | & $kubectl apply -f -
(Get-Content k8s/50-cronjob.yaml -Raw) -replace '__IMAGE__', $image | & $kubectl apply -f -

Write-Host "==> rollout"
& $kubectl -n foundry-monitor rollout status deploy/web --timeout=180s
& $kubectl -n foundry-monitor get pods,pvc,ingress -o wide
