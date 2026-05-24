$env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path','User')
$ErrorActionPreference = 'Stop'
$root = 'c:\Users\lewang2\OneDrive - Microsoft\Documents\WorkSpace - VSCode\foundry-retirement-monitor'
Set-Location $root

Write-Host '== Repackaging app =='
$zip = Join-Path $root 'deploy.zip'
if (Test-Path $zip) { Remove-Item $zip -Force }
Set-Location (Join-Path $root 'app')
Compress-Archive -Path host.json,function_app.py,foundry_monitor.py,requirements.txt,.funcignore -DestinationPath $zip -Force
Set-Location $root
Get-Item $zip | Format-Table Name,Length

Write-Host '== Deploying via OneDeploy =='
az functionapp deployment source config-zip `
  -g rg-foundry-monitor `
  -n func-znnzcoperxcfc `
  --src $zip `
  --build-remote true `
  -o json | Tee-Object -FilePath deploy-code-result.json | Out-Null

if ($LASTEXITCODE -ne 0) {
  Write-Host 'config-zip exit code:' $LASTEXITCODE
  Get-Content deploy-code-result.json
  exit 1
}
Write-Host '== Result =='
Get-Content deploy-code-result.json
