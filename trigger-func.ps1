$env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path','User')
$ErrorActionPreference = 'Stop'

Write-Host '== Getting master key =='
$keyJson = az functionapp keys list -g rg-foundry-monitor -n func-znnzcoperxcfc -o json
$keys = $keyJson | ConvertFrom-Json
$masterKey = $keys.masterKey
if (-not $masterKey) { throw 'no master key' }

Write-Host '== Triggering daily_check =='
$uri = 'https://func-znnzcoperxcfc.azurewebsites.net/admin/functions/daily_check'
$headers = @{ 'x-functions-key' = $masterKey; 'Content-Type' = 'application/json' }
try {
  $resp = Invoke-WebRequest -Uri $uri -Method Post -Headers $headers -Body '{}' -UseBasicParsing
  Write-Host ('Status: ' + $resp.StatusCode)
} catch {
  Write-Host ('Trigger error: ' + $_.Exception.Message)
  if ($_.Exception.Response) {
    $sr = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
    Write-Host $sr.ReadToEnd()
  }
}
