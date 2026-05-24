$env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path','User')
$r = az group show -n rg-foundry-monitor -o json 2>$null
if (-not $r) {
  Write-Host 'GONE'
  exit 0
}
$j = $r | ConvertFrom-Json
Write-Host ('EXISTS state=' + $j.properties.provisioningState)
