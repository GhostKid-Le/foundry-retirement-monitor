$env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path','User')
Start-Sleep -Seconds 45

Write-Host '== Listing blobs in history container =='
az storage blob list --account-name stznnzcoperxcfc --container-name history --auth-mode login --query '[].{name:name,size:properties.contentLength,lastModified:properties.lastModified}' -o table

Write-Host ''
Write-Host '== Recent invocations (App Insights) =='
$query = "requests | where timestamp > ago(15m) | where name == 'daily_check' | project timestamp, success, resultCode, duration_ms=duration | order by timestamp desc | take 5"
az monitor app-insights query --app appi-znnzcoperxcfc -g rg-foundry-monitor --analytics-query $query --query 'tables[0].rows' -o table

Write-Host ''
Write-Host '== Recent traces =='
$query2 = "traces | where timestamp > ago(15m) | where severityLevel >= 1 | project timestamp, severityLevel, message | order by timestamp desc | take 20"
az monitor app-insights query --app appi-znnzcoperxcfc -g rg-foundry-monitor --analytics-query $query2 --query 'tables[0].rows' -o table
