param(
  [int]$UploadWorkers = 4,
  [int]$UploadRequests = 8,
  [int]$ConversationTurns = 40,
  [double]$TimeoutSec = 10
)

$ErrorActionPreference = "Stop"
Write-Host "[INFO] Running v6 stress smoke..."
python v6_refactor_no_license/scripts/stress_smoke.py `
  --upload-workers $UploadWorkers `
  --upload-requests $UploadRequests `
  --conversation-turns $ConversationTurns `
  --timeout-sec $TimeoutSec
if ($LASTEXITCODE -ne 0) {
  Write-Host "[FAIL] stress smoke failed with exit code $LASTEXITCODE"
  exit $LASTEXITCODE
}
Write-Host "[PASS] stress smoke finished."
