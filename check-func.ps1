$env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path','User')
Write-Host '== functions =='
$f = az functionapp function list -g rg-foundry-monitor -n func-znnzcoperxcfc -o json 2>$null
if ($f) { ($f | ConvertFrom-Json) | ForEach-Object { Write-Host ('  ' + $_.name) } } else { Write-Host '  (none yet)' }

Write-Host '== last deployment =='
$d = az rest --method get --uri 'https://func-znnzcoperxcfc.scm.azurewebsites.net/api/deployments?$top=1' --resource 'https://management.azure.com' 2>$null
Write-Host $d

Write-Host '== app state =='
$s = az functionapp show -g rg-foundry-monitor -n func-znnzcoperxcfc --query 'state' -o tsv
Write-Host $s
