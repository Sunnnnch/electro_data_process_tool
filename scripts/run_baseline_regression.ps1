param(
    [switch]$Full
)

$ErrorActionPreference = "Stop"
$scriptPath = Join-Path $PSScriptRoot "baseline_regression.py"

if ($Full) {
    python $scriptPath --full
} else {
    python $scriptPath
}

exit $LASTEXITCODE

