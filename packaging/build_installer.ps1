Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$PackagingDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $PackagingDir
$DistDir = Join-Path $ProjectRoot "dist\\ElectroChemV6"
$IssFile = Join-Path $PackagingDir "installer.iss"

if (-not (Test-Path $DistDir)) {
    throw "Missing onedir build: $DistDir. Run build_onedir.ps1 first."
}

$Candidates = @(
    "${env:ProgramFiles(x86)}\\Inno Setup 6\\ISCC.exe",
    "${env:ProgramFiles}\\Inno Setup 6\\ISCC.exe",
    "${env:LocalAppData}\\Programs\\Inno Setup 6\\ISCC.exe"
)
$ISCC = $Candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

if (-not $ISCC) {
    throw "Inno Setup 6 not found. Install Inno Setup and rerun this script."
}

Write-Host "== ElectroChem V6 installer build ==" -ForegroundColor Cyan
Write-Host "Using ISCC: $ISCC"

Push-Location $PackagingDir
try {
    & $ISCC $IssFile
} finally {
    Pop-Location
}

Write-Host "Installer build completed." -ForegroundColor Green
