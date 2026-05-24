$env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path','User')

Write-Host '== Blobs in history container =='
az storage blob list --account-name stznnzcoperxcfc --container-name history --auth-mode login --query '[].{name:name,size:properties.contentLength,lastModified:properties.lastModified}' -o table

Write-Host ''
Write-Host '== Blobs in deploymentpackage =='
az storage blob list --account-name stznnzcoperxcfc --container-name deploymentpackage --auth-mode login --query '[].name' -o tsv
