$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$az = "C:\Program Files (x86)\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"

Write-Host "=== AppGw frontend IP / ports / listeners ==="
& $az network application-gateway frontend-port list -g rg-foundry-monitor --gateway-name agw-foundry-monitor -o table
Write-Host ""
& $az network application-gateway http-listener list -g rg-foundry-monitor --gateway-name agw-foundry-monitor --query "[].{n:name,proto:protocol,port:frontendPort.id,sslcert:sslCertificate.id,host:hostName,hosts:hostNames}" -o json
Write-Host ""
Write-Host "=== TCP test 443 to 20.59.39.98 ==="
$t = [System.Net.Sockets.TcpClient]::new()
$iar = $t.BeginConnect('20.59.39.98', 443, $null, $null)
$ok = $iar.AsyncWaitHandle.WaitOne(5000, $false)
Write-Host "443 connected: $($ok -and $t.Connected)"
$t.Close()
Write-Host "=== TCP test 80 to 20.59.39.98 ==="
$t = [System.Net.Sockets.TcpClient]::new()
$iar = $t.BeginConnect('20.59.39.98', 80, $null, $null)
$ok = $iar.AsyncWaitHandle.WaitOne(5000, $false)
Write-Host "80 connected: $($ok -and $t.Connected)"
$t.Close()
