$env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path','User')
$ErrorActionPreference = 'Stop'
$root = 'c:\Users\lewang2\OneDrive - Microsoft\Documents\WorkSpace - VSCode\foundry-retirement-monitor'
Set-Location $root

Write-Host '== Compiling bicep =='
az bicep build --file infra/main.bicep --outfile infra/main.json
if ($LASTEXITCODE -ne 0) { throw 'bicep build failed' }

$depName = 'foundry-fc1-' + (Get-Date -Format 'yyyyMMddHHmmss')
Write-Host ('== Deploying ' + $depName + ' ==')
az deployment sub create `
  --name $depName `
  --location westus2 `
  --template-file infra/main.json `
  --parameters environmentName=foundry-monitor location=westus2 recipientAddress=wang.le@microsoft.com `
  -o json | Tee-Object -FilePath 'deploy-result.json' | Out-Null

if ($LASTEXITCODE -ne 0) { throw 'deployment failed' }

$res = Get-Content 'deploy-result.json' -Raw | ConvertFrom-Json
Write-Host ''
Write-Host ('State: ' + $res.properties.provisioningState)
Write-Host ('Function: ' + $res.properties.outputs.AZURE_FUNCTION_NAME.value)
Write-Host ('Storage:  ' + $res.properties.outputs.AZURE_STORAGE_ACCOUNT.value)
Write-Host ('Sender:   ' + $res.properties.outputs.ACS_MANAGED_DOMAIN_HINT.value)
