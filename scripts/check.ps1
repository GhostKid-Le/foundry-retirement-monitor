$ErrorActionPreference = 'Continue'
$az = "C:\Program Files (x86)\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
Write-Host "=== NSG rules on nsg-snet-appgw ==="
& $az network nsg rule list -g rg-foundry-monitor --nsg-name nsg-snet-appgw --query "[].{n:name,prio:priority,dir:direction,acc:access,proto:protocol,src:sourceAddressPrefix,dport:destinationPortRange}" -o table
Write-Host ""
Write-Host "=== Subnet snet-appgw NSG attachment ==="
& $az network vnet subnet show -g rg-foundry-monitor --vnet-name vnet-foundry-monitor -n snet-appgw --query "networkSecurityGroup.id" -o tsv
Write-Host ""
Write-Host "=== HTTPS probe ==="
& "C:\Windows\System32\curl.exe" -k -s -o NUL -w "https=%{http_code}`n" --max-time 20 https://foundry-monitor.westus2.cloudapp.azure.com/healthz
& "C:\Windows\System32\curl.exe" -s -o NUL -w "http=%{http_code}`n" --max-time 20 http://foundry-monitor.westus2.cloudapp.azure.com/healthz
