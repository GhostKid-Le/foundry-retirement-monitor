# 部署脚本：把 Bicep + 镜像 + K8s manifests 一气呵成推上去
# 使用方法：
#   .\scripts\deploy.ps1                          # 全量部署
#   .\scripts\deploy.ps1 -SkipInfra              # 跳过 Bicep（基础设施没变时）
#   .\scripts\deploy.ps1 -SkipBuild              # 跳过镜像构建（代码没变时）
#
# 前置：az login 完成；docker desktop 或 az acr build 可用。
param(
    [switch]$SkipInfra,
    [switch]$SkipBuild,
    [string]$ResourceGroup = "rg-foundry-monitor",
    [string]$Location      = "westus2",
    [string]$AcrName       = "acrfoundrymonitor",
    [string]$AksName       = "aks-foundry-monitor",
    [string]$ImageRepo     = "foundry-monitor",
    [string]$ImageTag      = "latest"
)

$ErrorActionPreference = "Stop"
$env:Path += ";C:\Program Files (x86)\Microsoft SDKs\Azure\CLI2\wbin"

Set-Location (Join-Path $PSScriptRoot "..")

# ---------- 1. Infra ----------
if (-not $SkipInfra) {
    Write-Host "=== [1/4] Deploy Bicep ==="
    az group create -n $ResourceGroup -l $Location --tags project=foundry-retirement-monitor -o table | Out-Null
    az deployment group create -g $ResourceGroup -n foundry-monitor-infra `
        -f infra/main.bicep --parameters location=$Location -o table
}

# ---------- 2. Build & push image (ACR Tasks，不需要本地 Docker) ----------
$Image = "$AcrName.azurecr.io/$ImageRepo`:$ImageTag"
if (-not $SkipBuild) {
    Write-Host "=== [2/4] Build $Image via ACR Tasks ==="
    az acr build -r $AcrName -t "$ImageRepo`:$ImageTag" -f Dockerfile .
}

# ---------- 3. kube credentials ----------
Write-Host "=== [3/4] Get AKS credentials ==="
az aks get-credentials -g $ResourceGroup -n $AksName --overwrite-existing

# ---------- 4. Apply manifests ----------
Write-Host "=== [4/4] Apply K8s manifests ==="
kubectl apply -f k8s/00-namespace.yaml
kubectl apply -f k8s/10-pvc.yaml

# 检查 Secret 是否已存在；不存在时报错提醒
$secret = kubectl -n foundry-monitor get secret mailer-webhook --ignore-not-found -o name 2>$null
if (-not $secret) {
    Write-Warning "Secret 'mailer-webhook' 不存在！请先执行："
    Write-Warning "  kubectl -n foundry-monitor create secret generic mailer-webhook --from-literal=url='<POWER_AUTOMATE_URL>'"
    Write-Warning "继续部署其余资源；CronJob 启动前需补上该 Secret。"
}

# 用 sed 替换镜像占位符再 apply
(Get-Content k8s/30-web.yaml)      -replace '__IMAGE__', $Image | kubectl apply -f -
(Get-Content k8s/40-ingress.yaml)                                | kubectl apply -f -
(Get-Content k8s/50-cronjob.yaml)  -replace '__IMAGE__', $Image | kubectl apply -f -

Write-Host ""
Write-Host "=== Done ==="
$pip = az network public-ip show -g $ResourceGroup -n pip-agw-foundry-monitor --query "{ip:ipAddress, fqdn:dnsSettings.fqdn}" -o json | ConvertFrom-Json
Write-Host "Public IP : $($pip.ip)"
Write-Host "FQDN      : $($pip.fqdn)"
Write-Host "URL       : http://$($pip.fqdn)/"
