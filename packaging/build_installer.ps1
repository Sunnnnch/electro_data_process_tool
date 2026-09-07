param(
    [string]$AppVersion = "",
    [switch]$RequireSigning,
    [string]$IsccPath = "",
    [string]$WebView2OfflineInstaller = "",
    [string]$SourceRoot = "dist",
    [string]$OutputRoot = "dist_installer"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$PackagingDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $PackagingDir
. (Join-Path $PackagingDir "build_paths.ps1")
$SourceDistributionRoot = Assert-DistributionRoot $ProjectRoot $SourceRoot
$DistDir = Assert-ExpectedBuildPath $ProjectRoot (Join-Path $SourceDistributionRoot "ElectroChem") "$SourceRoot\ElectroChem"
$OutputDir = Assert-DistributionRoot $ProjectRoot $OutputRoot
$IssFile = Join-Path $PackagingDir "installer.iss"
$SignScript = Join-Path $PackagingDir "sign_windows_binary.ps1"

if (-not (Test-Path $DistDir)) {
    throw "Missing onedir build: $DistDir. Run build_onedir.ps1 first."
}

if (-not $AppVersion) {
    $configPy = Join-Path $ProjectRoot "src\electrochem_v6\config.py"
    $match = Select-String -Path $configPy -Pattern 'APP_VERSION\s*=\s*"([^"]+)"'
    if (-not $match) {
        throw "Unable to read APP_VERSION from $configPy"
    }
    $AppVersion = $match.Matches[0].Groups[1].Value
}
if ($AppVersion -notmatch '^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$') {
    throw "Invalid application version: $AppVersion"
}

if (-not $IsccPath) { $IsccPath = [string]$env:ELECTROCHEM_ISCC_PATH }
$Candidates = @(
    $IsccPath,
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "${env:LocalAppData}\Programs\Inno Setup 6\ISCC.exe"
)
$ISCC = $Candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if ($IsccPath -and -not (Test-Path -LiteralPath $IsccPath -PathType Leaf)) {
    throw "The supplied ISCC executable does not exist: $IsccPath"
}
if (-not $ISCC) {
    $IsccCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($IsccCommand) { $ISCC = $IsccCommand.Source }
}
if (-not $ISCC) {
    throw "Inno Setup 6 not found. Supply -IsccPath or ELECTROCHEM_ISCC_PATH (a workspace-local compiler is supported)."
}

$CompilerArguments = @("/DAppVersion=$AppVersion", "/DAppSourceDir=$DistDir", "/O$OutputDir")
if ($WebView2OfflineInstaller) {
    $OfflinePath = (Resolve-Path -LiteralPath $WebView2OfflineInstaller).ProviderPath
    if (-not (Test-Path -LiteralPath $OfflinePath -PathType Leaf) -or
        [IO.Path]::GetFileName($OfflinePath) -ne "MicrosoftEdgeWebView2RuntimeInstallerX64.exe") {
        throw "Supply the Microsoft Evergreen Standalone x64 installer named MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
    }
    $OfflineSignature = Get-AuthenticodeSignature -LiteralPath $OfflinePath
    if ($OfflineSignature.Status -ne [System.Management.Automation.SignatureStatus]::Valid -or
        -not $OfflineSignature.SignerCertificate -or
        $OfflineSignature.SignerCertificate.Subject -notmatch '(^|,\s*)O=Microsoft Corporation(,|$)') {
        throw "The optional WebView2 offline installer must have a valid Microsoft Authenticode signature"
    }
    $CompilerArguments += "/DWebView2OfflineInstaller=$OfflinePath"
}

Write-Host "== ElectroChem installer build ==" -ForegroundColor Cyan
Write-Host "Version: $AppVersion"
Write-Host "Using ISCC: $ISCC"

foreach ($ExecutableName in @("ElectroChem.exe", "ElectroChem-MCP.exe")) {
    $ApplicationExe = Join-Path $DistDir $ExecutableName
    if (-not (Test-Path -LiteralPath $ApplicationExe -PathType Leaf)) {
        throw "Missing application executable: $ApplicationExe. Rebuild the complete onedir first."
    }
    & $SignScript -Path $ApplicationExe -RequireSigning:$RequireSigning
}

$InstallerRelative = "$OutputRoot\ElectroChem-Setup-$AppVersion.exe"
$InstallerPath = Assert-ExpectedBuildPath $ProjectRoot (Join-Path $ProjectRoot $InstallerRelative) $InstallerRelative
$ChecksumPath = Assert-ExpectedBuildPath $ProjectRoot "$InstallerPath.sha256" "$InstallerRelative.sha256"
# Remove only these verified files so an old artifact cannot pass this build.
foreach ($ArtifactPath in @($InstallerPath, $ChecksumPath)) {
    if (Test-Path -LiteralPath $ArtifactPath) {
        if (-not (Test-Path -LiteralPath $ArtifactPath -PathType Leaf)) { throw "Expected an artifact file: $ArtifactPath" }
        Remove-Item -LiteralPath $ArtifactPath -Force
    }
}

Push-Location $PackagingDir
try {
    & $ISCC @CompilerArguments $IssFile
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}

if (-not (Test-Path $InstallerPath)) {
    throw "Installer output not found: $InstallerPath"
}

& $SignScript -Path $InstallerPath -RequireSigning:$RequireSigning

$Hash = Get-FileHash -Path $InstallerPath -Algorithm SHA256
$ChecksumPath = "$InstallerPath.sha256"
"$($Hash.Hash.ToLowerInvariant()) *$([System.IO.Path]::GetFileName($InstallerPath))" |
    Set-Content -Path $ChecksumPath -Encoding ascii

Write-Host "Installer build completed." -ForegroundColor Green
Write-Host "Output: $InstallerPath"
Write-Host "SHA-256: $ChecksumPath"
