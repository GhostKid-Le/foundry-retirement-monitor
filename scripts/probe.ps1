$ProgressPreference = 'SilentlyContinue'
try {
  $r = Invoke-WebRequest -Uri 'https://foundry-monitor.westus2.cloudapp.azure.com/healthz' -TimeoutSec 30 -UseBasicParsing
  "https=$($r.StatusCode) body=$($r.Content)"
} catch {
  "https-err=$($_.Exception.Message)"
}
try {
  $r2 = Invoke-WebRequest -Uri 'http://foundry-monitor.westus2.cloudapp.azure.com/healthz' -TimeoutSec 30 -UseBasicParsing -MaximumRedirection 0 -ErrorAction Stop
  "http=$($r2.StatusCode)"
} catch {
  if ($_.Exception.Response) { "http=$([int]$_.Exception.Response.StatusCode)" } else { "http-err=$($_.Exception.Message)" }
}
