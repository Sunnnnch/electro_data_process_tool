param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [switch]$RequireSigning
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ResolvedPath = (Resolve-Path -LiteralPath $Path).Path
$Thumbprint = [string]$env:ELECTROCHEM_SIGN_CERT_SHA1
if (-not $Thumbprint) {
    if ($RequireSigning) {
        throw "Signing is required, but ELECTROCHEM_SIGN_CERT_SHA1 is not configured"
    }
    Write-Warning "Skipping Authenticode signing for local-test artifact: $ResolvedPath"
    return
}

$ExistingSignature = Get-AuthenticodeSignature -FilePath $ResolvedPath
if (
    $ExistingSignature.Status -eq [System.Management.Automation.SignatureStatus]::Valid -and
    $ExistingSignature.SignerCertificate -and
    $ExistingSignature.SignerCertificate.Thumbprint -eq $Thumbprint
) {
    Write-Host "Existing Authenticode signature is valid: $ResolvedPath" -ForegroundColor Green
    return
}

$Candidates = @(
    "${env:ProgramFiles(x86)}\Windows Kits\10\App Certification Kit\signtool.exe",
    "${env:ProgramFiles}\Windows Kits\10\App Certification Kit\signtool.exe"
)
$SignTool = $Candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $SignTool) {
    $KitBin = "${env:ProgramFiles(x86)}\Windows Kits\10\bin"
    if (Test-Path $KitBin) {
        $SignTool = Get-ChildItem $KitBin -Filter signtool.exe -Recurse -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending |
            Select-Object -First 1 -ExpandProperty FullName
    }
}
if (-not $SignTool) {
    throw "signtool.exe was not found"
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
Write-Host "Authenticode signature verified: $ResolvedPath" -ForegroundColor Green
