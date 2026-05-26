$ErrorActionPreference = 'Continue'
$az = "C:\Program Files (x86)\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
Write-Host "=== AppGw operational state ==="
& $az network application-gateway show -g rg-foundry-monitor -n agw-foundry-monitor --query "{prov:provisioningState,op:operationalState}" -o json
Write-Host ""
Write-Host "=== AppGw backend health ==="
& $az network application-gateway show-backend-health -g rg-foundry-monitor -n agw-foundry-monitor --query "backendAddressPools[].backendHttpSettingsCollection[].servers[].{addr:address,health:health}" -o table
Write-Host ""
Write-Host "=== Test 443 TCP via tnc ==="
Test-NetConnection -ComputerName foundry-monitor.westus2.cloudapp.azure.com -Port 443 -WarningAction SilentlyContinue | Select-Object ComputerName, RemoteAddress, TcpTestSucceeded | Format-List
Write-Host "=== Test 80 TCP via tnc ==="
Test-NetConnection -ComputerName foundry-monitor.westus2.cloudapp.azure.com -Port 80 -WarningAction SilentlyContinue | Select-Object ComputerName, RemoteAddress, TcpTestSucceeded | Format-List
