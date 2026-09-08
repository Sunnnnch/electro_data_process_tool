param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [switch]$RequireSigning,
    [string]$SignToolPath = "",
    [string]$ReceiptDirectory = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot 'windows_signing.ps1')

$ResolvedPath = (Resolve-Path -LiteralPath $Path).Path
$Thumbprint = [string]$env:ELECTROCHEM_SIGN_CERT_SHA1
if (-not $Thumbprint) {
    if ($RequireSigning) {
        throw "Signing is required, but ELECTROCHEM_SIGN_CERT_SHA1 is not configured"
    }
    Write-Warning "Skipping Authenticode signing for local-test artifact: $ResolvedPath"
    return
}
if ($Thumbprint -notmatch '^[0-9a-fA-F]{40}$') { throw 'ELECTROCHEM_SIGN_CERT_SHA1 must be a 40-character certificate thumbprint' }
$SignTool = Get-VerifiedSignTool $SignToolPath

$ExistingSignature = Get-AuthenticodeSignature -FilePath $ResolvedPath
if (
    $ExistingSignature.Status -eq [System.Management.Automation.SignatureStatus]::Valid -and
    $ExistingSignature.SignerCertificate -and
    $ExistingSignature.SignerCertificate.Thumbprint -eq $Thumbprint
) {
    Assert-PublisherSignature $ExistingSignature $Thumbprint
    Write-PublisherSigningReceipt $ResolvedPath $ReceiptDirectory $ExistingSignature
    Write-Host "Existing Authenticode signature is valid: $ResolvedPath" -ForegroundColor Green
    return
}

$TimestampUrl = [string]$env:ELECTROCHEM_TIMESTAMP_URL
if (-not $TimestampUrl) {
    $TimestampUrl = "http://timestamp.digicert.com"
}
& $SignTool sign /sha1 $Thumbprint /fd SHA256 /tr $TimestampUrl /td SHA256 $ResolvedPath
if ($LASTEXITCODE -ne 0) {
    throw "Authenticode signing failed with exit code $LASTEXITCODE"
}
& $SignTool verify /pa /v $ResolvedPath
if ($LASTEXITCODE -ne 0) {
    throw "Authenticode signature verification failed with exit code $LASTEXITCODE"
}
$VerifiedSignature = Get-AuthenticodeSignature -LiteralPath $ResolvedPath
Assert-PublisherSignature $VerifiedSignature $Thumbprint
Write-PublisherSigningReceipt $ResolvedPath $ReceiptDirectory $VerifiedSignature
Write-Host "Authenticode signature verified: $ResolvedPath" -ForegroundColor Green
