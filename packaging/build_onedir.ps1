Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$PackagingDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $PackagingDir
$VenvDir = Join-Path $PackagingDir ".venv-pack"
$RequirementsFile = Join-Path $PackagingDir "requirements-pack.txt"
$SpecFile = Join-Path $PackagingDir "electrochem_v6.spec"
$PythonExe = Join-Path $VenvDir "Scripts\\python.exe"
$PyInstallerExe = Join-Path $VenvDir "Scripts\\pyinstaller.exe"

Write-Host "== ElectroChem V6 packaging (onedir) ==" -ForegroundColor Cyan
Write-Host "Project root: $ProjectRoot"
Write-Host "Packaging dir: $PackagingDir"

if (-not (Test-Path $VenvDir)) {
    Write-Host "Creating packaging virtual environment..." -ForegroundColor Yellow
    python -m venv $VenvDir
}

Write-Host "Installing packaging dependencies..." -ForegroundColor Yellow
& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -r $RequirementsFile

Write-Host "Cleaning previous build outputs..." -ForegroundColor Yellow
$BuildDir = Join-Path $ProjectRoot "build"
$DistDir = Join-Path $ProjectRoot "dist"
if (Test-Path $BuildDir) { Remove-Item $BuildDir -Recurse -Force }
if (Test-Path (Join-Path $DistDir "ElectroChemV6")) { Remove-Item (Join-Path $DistDir "ElectroChemV6") -Recurse -Force }

Write-Host "Running PyInstaller..." -ForegroundColor Yellow
Push-Location $ProjectRoot
try {
    & $PyInstallerExe --noconfirm --clean $SpecFile
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "Build completed." -ForegroundColor Green
Write-Host "Output: $DistDir\\ElectroChemV6"
Write-Host "Next step: run build_installer.ps1 to create an installer."
