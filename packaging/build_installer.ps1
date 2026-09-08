param(
    [string]$AppVersion = "",
    [switch]$RequireSigning,
    [string]$SignToolPath = "",
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
. (Join-Path $PackagingDir "installer_prerequisites.ps1")
. (Join-Path $PackagingDir "windows_signing.ps1")
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
$OfflineMetadata = $null
$ArtifactSuffix = ""
if ($WebView2OfflineInstaller) {
    $OfflineMetadata = Get-ValidatedWebView2Installer $WebView2OfflineInstaller
    $ArtifactSuffix = "-offline"
    $CompilerArguments += "/DWebView2OfflineInstaller=$($OfflineMetadata.path)"
    $CompilerArguments += "/DWebView2OfflineSHA256=$($OfflineMetadata.sha256)"
}
$DependencyInventory = @(Get-InstallerDependencyInventory $DistDir)
$SigningEnabled = [bool]$RequireSigning -or [bool]$env:ELECTROCHEM_SIGN_CERT_SHA1
$SigningReceiptDir = ''
if ($SigningEnabled) {
    if (-not $env:ELECTROCHEM_SIGN_CERT_SHA1) {
        throw 'Signing is required, but ELECTROCHEM_SIGN_CERT_SHA1 is not configured'
    }
    $SignToolPath = Get-VerifiedSignTool $SignToolPath
    $HostExe = (Get-Process -Id $PID).Path
    if ([IO.Path]::GetFileName($HostExe) -notin @('pwsh.exe', 'powershell.exe')) {
        $HostExe = Join-Path $PSHOME 'powershell.exe'
    }
    $ReceiptRelative = "$OutputRoot\signing-$([guid]::NewGuid().ToString('N'))"
    $SigningReceiptDir = Assert-ExpectedBuildPath $ProjectRoot (Join-Path $ProjectRoot $ReceiptRelative) $ReceiptRelative
    New-Item -ItemType Directory -Path $SigningReceiptDir | Out-Null
    $SignCommand = New-InnoPublisherSignCommand $HostExe $SignScript $SigningReceiptDir $SignToolPath
    $CompilerArguments += '/DPublisherSigning'
    $CompilerArguments += "/Selectrochem_publisher=$SignCommand"
}

Write-Host "== ElectroChem installer build ==" -ForegroundColor Cyan
Write-Host "Version: $AppVersion"
Write-Host "Using ISCC: $ISCC"

foreach ($ExecutableName in @("ElectroChem.exe", "ElectroChem-MCP.exe")) {
    $ApplicationExe = Join-Path $DistDir $ExecutableName
    if (-not (Test-Path -LiteralPath $ApplicationExe -PathType Leaf)) {
        throw "Missing application executable: $ApplicationExe. Rebuild the complete onedir first."
    }
    & $SignScript -Path $ApplicationExe -RequireSigning:$RequireSigning -SignToolPath $SignToolPath
}

$InstallerRelative = "$OutputRoot\ElectroChem-Setup-$AppVersion$ArtifactSuffix.exe"
$InstallerPath = Assert-ExpectedBuildPath $ProjectRoot (Join-Path $ProjectRoot $InstallerRelative) $InstallerRelative
$ChecksumPath = Assert-ExpectedBuildPath $ProjectRoot "$InstallerPath.sha256" "$InstallerRelative.sha256"
$ManifestPath = Assert-ExpectedBuildPath $ProjectRoot "$InstallerPath.dependencies.json" "$InstallerRelative.dependencies.json"
$ManifestChecksumPath = Assert-ExpectedBuildPath $ProjectRoot "$ManifestPath.sha256" "$InstallerRelative.dependencies.json.sha256"
# Remove only these verified files so an old artifact cannot pass this build.
foreach ($ArtifactPath in @($InstallerPath, $ChecksumPath, $ManifestPath, $ManifestChecksumPath)) {
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

& $SignScript -Path $InstallerPath -RequireSigning:$RequireSigning -SignToolPath $SignToolPath
$UninstallerReceipts = @()
if ($SigningEnabled) {
    $UninstallerReceipts = @(Get-ChildItem -LiteralPath $SigningReceiptDir -Filter 'uninstaller-*.json' -File |
        ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json })
    if ($UninstallerReceipts.Count -eq 0) {
        throw 'No verified signed-uninstaller receipt was produced by Inno Setup'
    }
    foreach ($Receipt in $UninstallerReceipts) {
        if ($Receipt.status -ne 'Valid' -or $Receipt.thumbprint -ne $env:ELECTROCHEM_SIGN_CERT_SHA1) {
            throw 'The embedded uninstaller signing receipt does not match the configured publisher'
        }
    }
}

$Hash = Get-FileHash -Path $InstallerPath -Algorithm SHA256
$ChecksumPath = "$InstallerPath.sha256"
"$($Hash.Hash.ToLowerInvariant()) *$([System.IO.Path]::GetFileName($InstallerPath))" |
    Set-Content -Path $ChecksumPath -Encoding ascii

$BundledRuntime = $null
if ($OfflineMetadata) {
    # Never leak the build machine's absolute prerequisite path into artifacts.
    $BundledRuntime = [ordered]@{}
    foreach ($Key in $OfflineMetadata.Keys) {
        if ($Key -ne 'path') { $BundledRuntime[$Key] = $OfflineMetadata[$Key] }
    }
}
$DependencyManifest = [ordered]@{
    schemaVersion = 1
    applicationVersion = $AppVersion
    variant = if ($OfflineMetadata) { 'offline' } else { 'standard' }
    signing = [ordered]@{ enabled = $SigningEnabled; uninstaller = $UninstallerReceipts }
    installer = [ordered]@{ filename = [IO.Path]::GetFileName($InstallerPath); sha256 = $Hash.Hash.ToLowerInvariant() }
    platform = [ordered]@{ os = 'Windows'; minimumBuild = 19045; architecture = 'x64'; arm64 = 'not-supported-by-installer' }
    prerequisites = [ordered]@{
        webview2 = [ordered]@{ minimumMajor = 120; bundled = [bool]$OfflineMetadata; installer = $BundledRuntime }
        dotnetFramework = [ordered]@{ minimumVersion = '4.6.2'; suppliedByTargetWindows = $true; bundledInstaller = $false }
        visualCpp = [ordered]@{ distribution = 'application-local'; bundledInstaller = $false }
        python = [ordered]@{ version = '3.12'; distribution = 'application-local' }
    }
    dependencyFiles = $DependencyInventory
    runtimeRequirements = @(Get-Content -LiteralPath (Join-Path $DistDir 'runtime-requirements.txt') | Where-Object { $_.Trim() })
}
$DependencyManifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ManifestPath -Encoding utf8
$ManifestHash = (Get-FileHash -LiteralPath $ManifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
"$ManifestHash *$([IO.Path]::GetFileName($ManifestPath))" | Set-Content -LiteralPath $ManifestChecksumPath -Encoding ascii

Write-Host "Installer build completed." -ForegroundColor Green
Write-Host "Output: $InstallerPath"
Write-Host "SHA-256: $ChecksumPath"
Write-Host "Dependency manifest: $ManifestPath"
Write-Host "Dependency manifest SHA-256: $ManifestChecksumPath"
