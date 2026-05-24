$ErrorActionPreference = 'Stop'
$cred = az webapp deployment list-publishing-credentials -g rg-foundry-monitor -n func-znnzcoperxcfc --query '{u:publishingUserName,p:publishingPassword}' -o json | ConvertFrom-Json
$pair = $cred.u + ':' + $cred.p
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pair))
$headers = @{ Authorization = "Basic $b64" }
$list = Invoke-RestMethod -Uri 'https://func-znnzcoperxcfc.scm.azurewebsites.net/api/deployments/3d20330e-9e67-48b3-8c51-5d174ae6d5c2/log' -Headers $headers
foreach ($l in $list) {
  Write-Host ("[{0}] {1}" -f $l.log_time, $l.message)
  if ($l.details_url) {
    $det = Invoke-RestMethod -Uri $l.details_url -Headers $headers
    foreach ($d in $det) { Write-Host ("    -> " + $d.message) }
  }
}
