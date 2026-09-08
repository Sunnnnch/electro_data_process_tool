# Shared signing checks and Inno command construction. No signing on import.
Set-StrictMode -Version Latest

function Assert-PublisherSignature {
    param([object]$Signature, [string]$Thumbprint)
    if ($Signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid -or
        -not $Signature.SignerCertificate -or
        $Signature.SignerCertificate.Thumbprint -ne $Thumbprint) {
        throw 'The binary does not have a valid Authenticode signature from the configured publisher certificate'
    }
}

function Get-VerifiedSignTool {
    param([string]$SignToolPath = '')
    if (-not $SignToolPath) { $SignToolPath = [string]$env:ELECTROCHEM_SIGNTOOL_PATH }
    if ($SignToolPath) {
        if (-not (Test-Path -LiteralPath $SignToolPath -PathType Leaf)) {
            throw "The supplied SignTool executable does not exist: $SignToolPath"
        }
        $Selected = (Resolve-Path -LiteralPath $SignToolPath).ProviderPath
    } else {
        $Candidates = @(
            "${env:ProgramFiles(x86)}\Windows Kits\10\App Certification Kit\signtool.exe",
            "${env:ProgramFiles}\Windows Kits\10\App Certification Kit\signtool.exe"
        )
        $Selected = $Candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
        if (-not $Selected) {
            $KitBin = "${env:ProgramFiles(x86)}\Windows Kits\10\bin"
            if (Test-Path -LiteralPath $KitBin -PathType Container) {
                $Selected = Get-ChildItem -LiteralPath $KitBin -Filter signtool.exe -Recurse -File |
                    Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
            }
        }
    }
    if (-not $Selected) { throw 'signtool.exe was not found. Supply -SignToolPath or ELECTROCHEM_SIGNTOOL_PATH.' }
    $ToolSignature = Get-AuthenticodeSignature -LiteralPath $Selected
    if ($ToolSignature.Status -ne [System.Management.Automation.SignatureStatus]::Valid -or
        -not $ToolSignature.SignerCertificate -or
        $ToolSignature.SignerCertificate.Subject -notmatch '(^|,\s*)O=Microsoft Corporation(,|$)') {
        throw 'SignTool must be an executable with a valid Microsoft Authenticode signature'
    }
    return $Selected
}

function ConvertTo-InnoQuotedPath {
    param([string]$Path)
    if (-not $Path -or $Path -match '["\r\n]') { throw 'Invalid path in the Inno signing command' }
    # Inno substitutes $q (quote), $f (quoted target) and $$ (literal dollar).
    # The callback uses PowerShell -File, never -Command or a cmd.exe wrapper.
    return '$q' + $Path.Replace('$', '$$') + '$q'
}

function New-InnoPublisherSignCommand {
    param([string]$PowerShellPath, [string]$ScriptPath, [string]$ReceiptDirectory, [string]$SignToolPath)
    $Parts = @(
        (ConvertTo-InnoQuotedPath $PowerShellPath),
        '-NoProfile -NonInteractive -WindowStyle Hidden -File',
        (ConvertTo-InnoQuotedPath $ScriptPath),
        '-Path $f -RequireSigning -ReceiptDirectory',
        (ConvertTo-InnoQuotedPath $ReceiptDirectory),
        '-SignToolPath',
        (ConvertTo-InnoQuotedPath $SignToolPath)
    )
    return $Parts -join ' '
}

function Write-PublisherSigningReceipt {
    param([string]$Path, [string]$ReceiptDirectory, [object]$Signature)
    if (-not $ReceiptDirectory) { return }
    if (-not (Test-Path -LiteralPath $ReceiptDirectory -PathType Container)) {
        throw 'The signing receipt directory must already exist'
    }
    $Leaf = [IO.Path]::GetFileName($Path)
    $Role = if ($Leaf -match '^uninst\.e(?:32|64)\.tmp$') { 'uninstaller' } else { 'setup' }
    $Hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    $Receipt = [ordered]@{
        role = $Role
        filename = $Leaf
        sha256 = $Hash
        status = [string]$Signature.Status
        thumbprint = $Signature.SignerCertificate.Thumbprint
        subject = $Signature.SignerCertificate.Subject
    }
    $Receipt | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $ReceiptDirectory "$Role-$Hash.json") -Encoding utf8
}
