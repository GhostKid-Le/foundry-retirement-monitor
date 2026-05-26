param(
  [string]$WebhookUrl
)
$ErrorActionPreference = 'Stop'
$env:Path += ";C:\Program Files (x86)\Microsoft SDKs\Azure\CLI2\wbin;C:\Users\lewang2\.azure-kubectl;C:\Users\lewang2\.azure-kubelogin"
Set-Location $PSScriptRoot\..

Write-Host "==> nodes"
kubectl get nodes

Write-Host "==> namespace + pvc"
kubectl apply -f k8s/00-namespace.yaml
kubectl apply -f k8s/10-pvc.yaml

if ($WebhookUrl) {
  Write-Host "==> creating mailer-webhook secret"
  kubectl -n foundry-monitor delete secret mailer-webhook --ignore-not-found
  kubectl -n foundry-monitor create secret generic mailer-webhook --from-literal=url=$WebhookUrl
} else {
  $exists = kubectl -n foundry-monitor get secret mailer-webhook -o name 2>$null
  if (-not $exists) { Write-Warning "mailer-webhook secret missing; CronJob will fail" }
}

$image = "acrfoundrymonitor.azurecr.io/foundry-monitor:latest"
Write-Host "==> apply web ($image)"
(Get-Content k8s/30-web.yaml -Raw) -replace '__IMAGE__', $image | kubectl apply -f -

Write-Host "==> apply cronjob ($image)"
(Get-Content k8s/50-cronjob.yaml -Raw) -replace '__IMAGE__', $image | kubectl apply -f -

Write-Host "==> apply ingress"
kubectl apply -f k8s/40-ingress.yaml

Write-Host "==> wait rollout"
kubectl -n foundry-monitor rollout status deploy/web --timeout=180s

Write-Host "==> resources"
kubectl -n foundry-monitor get all,ingress
