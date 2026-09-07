param([string]$PythonPath = "", [string]$OutputRoot = "dist")

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$PackagingDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $PackagingDir
. (Join-Path $PackagingDir "build_paths.ps1")
$VenvDir = Assert-ExpectedBuildPath $ProjectRoot (Join-Path $PackagingDir ".venv-pack") "packaging\.venv-pack"
$BuildDir = Assert-ExpectedBuildPath $ProjectRoot (Join-Path $ProjectRoot "build\ElectroChemV6") "build\ElectroChemV6"
$DistributionRoot = Assert-DistributionRoot $ProjectRoot $OutputRoot
$DistRelative = "$OutputRoot\ElectroChem"
$DistDir = Assert-ExpectedBuildPath $ProjectRoot (Join-Path $DistributionRoot "ElectroChem") $DistRelative
$RequirementsFile = Join-Path $PackagingDir "requirements-pack.txt"
$SpecFile = Join-Path $PackagingDir "electrochem_v6.spec"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"

Write-Host "ElectroChem: Python 3.12 onedir build" -ForegroundColor Cyan
if (-not (Test-Path -LiteralPath $VenvDir)) {
    $PythonArgs = @()
    if (-not $PythonPath) {
        if (Get-Command py -ErrorAction SilentlyContinue) {
            $PythonPath = "py"
            $PythonArgs = @("-3.12")
        } else { $PythonPath = "python" }
    }
    & $PythonPath @PythonArgs -c "import sys,struct; assert sys.version_info[:2] == (3, 12) and struct.calcsize('P') == 8, 'Packaging requires 64-bit Python 3.12'"
    if ($LASTEXITCODE -ne 0) { throw "Packaging requires Python 3.12" }
    & $PythonPath @PythonArgs -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { throw "Unable to create packaging environment" }
}
& $PythonExe -c "import sys,struct; assert sys.version_info[:2] == (3, 12) and struct.calcsize('P') == 8, 'Recreate packaging venv with 64-bit Python 3.12'"
if ($LASTEXITCODE -ne 0) { throw "The packaging environment must use Python 3.12" }
# Propagate bounded, noninteractive options into isolated wheel-build subprocesses
# too, then restore this PowerShell session's previous environment.
$PipSettings = @{ PIP_NO_CACHE_DIR = "1"; PIP_DISABLE_PIP_VERSION_CHECK = "1"; PIP_NO_INPUT = "1"; PIP_DEFAULT_TIMEOUT = "30"; PIP_RETRIES = "1" }
$PreviousPipSettings = @{}
foreach ($SettingName in $PipSettings.Keys) {
    $PreviousPipSettings[$SettingName] = [Environment]::GetEnvironmentVariable($SettingName, "Process")
    [Environment]::SetEnvironmentVariable($SettingName, $PipSettings[$SettingName], "Process")
}
try {
    # Python 3.12's bundled pip may precede default Windows trust-store support.
    # Keep TLS verification enabled while honoring the operating system's roots.
    & $PythonExe -I -m pip --disable-pip-version-check --no-input --timeout 30 --retries 1 install --no-cache-dir --use-feature=truststore "pip==25.3"
    if ($LASTEXITCODE -ne 0) { throw "Unable to install pinned packaging pip" }
    & $PythonExe -I -m pip --disable-pip-version-check --no-input --timeout 30 --retries 1 install --no-cache-dir -r $RequirementsFile
    if ($LASTEXITCODE -ne 0) { throw "Unable to install packaging dependencies" }
} finally {
    foreach ($SettingName in $PreviousPipSettings.Keys) {
        [Environment]::SetEnvironmentVariable($SettingName, $PreviousPipSettings[$SettingName], "Process")
    }
}

# Only these two application-owned outputs may be removed, never all of build/.
Remove-CheckedBuildDirectory $ProjectRoot $BuildDir "build\ElectroChemV6"
Remove-CheckedBuildDirectory $ProjectRoot $DistDir $DistRelative
$PreviousPyInstallerConfig = [Environment]::GetEnvironmentVariable("PYINSTALLER_CONFIG_DIR", "Process")
$env:PYINSTALLER_CONFIG_DIR = Join-Path $BuildDir ".pyinstaller-cache"
Push-Location $ProjectRoot
try {
    & $PythonExe -m PyInstaller --noconfirm --clean --workpath $BuildDir --distpath (Split-Path -Parent $DistDir) $SpecFile
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
    [Environment]::SetEnvironmentVariable("PYINSTALLER_CONFIG_DIR", $PreviousPyInstallerConfig, "Process")
}

$DistDir = Assert-ExpectedBuildPath $ProjectRoot $DistDir $DistRelative
foreach ($ExecutableName in @("ElectroChem.exe", "ElectroChem-MCP.exe")) {
    if (-not (Test-Path -LiteralPath (Join-Path $DistDir $ExecutableName) -PathType Leaf)) {
        throw "Missing built executable: $ExecutableName"
    }
}
# The zip/onedir is deliberately portable; the installer excludes this marker.
Set-Content -LiteralPath (Join-Path $DistDir "portable.marker") -Value "portable-v1" -Encoding ascii
& $PythonExe -m pip freeze --all | Set-Content -LiteralPath (Join-Path $DistDir "runtime-requirements.txt") -Encoding utf8
if ($LASTEXITCODE -ne 0) { throw "Unable to record packaging dependencies" }
Write-Host "Build completed: $DistDir" -ForegroundColor Green
