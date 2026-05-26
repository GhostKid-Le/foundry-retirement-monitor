$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$kubectl = "C:\Users\lewang2\.azure-kubectl\kubectl.exe"
Write-Host "=== AGIC pod ==="
& $kubectl -n kube-system get pods -l app=ingress-appgw -o wide
Write-Host ""
Write-Host "=== Ingress status ==="
& $kubectl -n foundry-monitor get ingress -o wide
Write-Host ""
Write-Host "=== Certificate status ==="
& $kubectl -n foundry-monitor get certificate,secret -o wide
Write-Host ""
Write-Host "=== Re-apply ingress to trigger AGIC reconcile ==="
& $kubectl -n foundry-monitor annotate ingress --all "force-reconcile=$(Get-Date -Format o)" --overwrite
Write-Host ""
Write-Host "=== AGIC recent logs (errors) ==="
& $kubectl -n kube-system logs -l app=ingress-appgw --tail=40
