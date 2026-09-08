param(
    [Parameter(Mandatory = $true)][string]$Tag,
    [Parameter(Mandatory = $true)][string]$ExpectedCommit,
    [Parameter(Mandatory = $true)][string]$PortableZip,
    [Parameter(Mandatory = $true)][string]$Installer,
    [string]$OfflineInstaller = "",
    [string]$WebView2Installer = "",
    [string]$Remote = "origin",
    [string]$TargetBranch = "",
    [string]$PythonPath = "python",
    [switch]$VerifyOnly,
    [switch]$VerifyRemoteTag
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Validator = Join-Path $PSScriptRoot "release_validation.py"
$Arguments = @($Validator, "--tag", $Tag, "--expected-commit", $ExpectedCommit,
               "--portable-zip", $PortableZip, "--installer", $Installer, "--remote", $Remote)
if ($VerifyRemoteTag) { $Arguments += "--verify-remote-tag" }
if ($OfflineInstaller -or $WebView2Installer) {
    if (-not $OfflineInstaller -or -not $WebView2Installer) {
        throw "OfflineInstaller and WebView2Installer are required together; no refs were published"
    }
    $Arguments += @("--offline-installer", $OfflineInstaller, "--webview2-installer", $WebView2Installer)
}
& $PythonPath @Arguments
if ($LASTEXITCODE -ne 0) { throw "Release validation failed; no refs were published" }
if ($VerifyOnly) { return }
if (-not $TargetBranch) { throw "Explicit -TargetBranch is required; no branch is chosen automatically" }
git check-ref-format --branch $TargetBranch | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Invalid target branch; no refs were published" }

# Explicit caller action only. CI never invokes this write path automatically.
# Both refs move together after source, checksums, versions and signatures pass.
git push --atomic $Remote "${ExpectedCommit}:refs/heads/${TargetBranch}" "refs/tags/${Tag}:refs/tags/${Tag}"
if ($LASTEXITCODE -ne 0) {
    throw "Release refs were not published; verify remote state before retrying"
}
