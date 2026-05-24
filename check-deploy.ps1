$env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path','User')
$names = az deployment sub list --query "[?starts_with(name,'foundry-fc1-')].name" -o tsv
foreach ($n in $names) {
  $s = az deployment sub show -n $n --query 'properties.provisioningState' -o tsv 2>$null
  Write-Host ($n + ' -> ' + $s)
}
$rg = az group show -n rg-foundry-monitor -o json 2>$null
if ($rg) {
  Write-Host '== Resources =='
  az resource list -g rg-foundry-monitor --query '[].{name:name,type:type,state:provisioningState}' -o table
}
