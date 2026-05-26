$k = "C:\Users\lewang2\.azure-kubectl\kubectl.exe"
Write-Host "=== certificates ==="
& $k -n foundry-monitor get certificate
Write-Host "=== orders ==="
& $k -n foundry-monitor get orders
Write-Host "=== challenges ==="
& $k -n foundry-monitor get challenges
Write-Host "=== ingress ==="
& $k -n foundry-monitor get ingress
