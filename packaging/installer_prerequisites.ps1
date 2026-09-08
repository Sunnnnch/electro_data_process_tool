# Read-only validation shared by installer builds and packaging tests.
Set-StrictMode -Version Latest

function Assert-WebView2InstallerMetadata {
    param([object]$Signature)
    if ($Signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid -or
        -not $Signature.SignerCertificate -or
        $Signature.SignerCertificate.Subject -notmatch '(^|,\s*)O=Microsoft Corporation(,|$)') {
        throw "The WebView2 offline installer must have a valid Microsoft Authenticode signature"
    }
}

function Get-ValidatedWebView2Installer {
    param([string]$Path)
    $Resolved = (Resolve-Path -LiteralPath $Path).ProviderPath
    if (-not (Test-Path -LiteralPath $Resolved -PathType Leaf) -or
        [IO.Path]::GetFileName($Resolved) -ne "MicrosoftEdgeWebView2RuntimeInstallerX64.exe") {
        throw "Supply the Microsoft Evergreen Standalone x64 installer named MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
    }
    $InitialHash = (Get-FileHash -LiteralPath $Resolved -Algorithm SHA256).Hash.ToLowerInvariant()
    $Signature = Get-AuthenticodeSignature -LiteralPath $Resolved
    $VersionInfo = (Get-Item -LiteralPath $Resolved).VersionInfo
    Assert-WebView2InstallerMetadata $Signature
    $PackagingPython = Join-Path $PSScriptRoot '.venv-pack\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $PackagingPython -PathType Leaf)) {
        throw 'The packaging Python environment is required to inspect the signed WebView2 payload. Run build_onedir.ps1 first.'
    }
    $PayloadJson = & $PackagingPython -I (Join-Path $PSScriptRoot 'read_webview2_payload.py') $Resolved
    if ($LASTEXITCODE -ne 0) { throw 'Unable to validate the Runtime version in the signed WebView2 payload.' }
    $Payload = $PayloadJson | ConvertFrom-Json
    if ((Get-FileHash -LiteralPath $Resolved -Algorithm SHA256).Hash.ToLowerInvariant() -ne $InitialHash) {
        throw 'WebView2 installer changed while its signature and payload were being verified.'
    }
    return [ordered]@{
        path = $Resolved
        filename = [IO.Path]::GetFileName($Resolved)
        version = $Payload.version
        versionSource = $Payload.versionSource
        runtimeAppId = $Payload.runtimeAppId
        runtimePackage = $Payload.runtimePackage
        runtimePackageSha256 = $Payload.runtimePackageSha256
        wrapperVersion = [string]$VersionInfo.ProductVersion
        sha256 = $InitialHash
        bytes = (Get-Item -LiteralPath $Resolved).Length
        signature = [ordered]@{
            status = [string]$Signature.Status
            subject = $Signature.SignerCertificate.Subject
            thumbprint = $Signature.SignerCertificate.Thumbprint
        }
    }
}

function Get-InstallerDependencyInventory {
    param([string]$Distribution)
    # pywebview 4.4.1 uses WinForms/.NET Framework. Python/scientific native
    # runtime files are carried by the onedir, not supplied by a global Python.
    $Required = @(
        'runtime-requirements.txt',
        '_internal\python312.dll',
        '_internal\VCRUNTIME140.dll',
        '_internal\VCRUNTIME140_1.dll',
        '_internal\ucrtbase.dll',
        '_internal\clr_loader\ffi\dlls\amd64\ClrLoader.dll',
        '_internal\pythonnet\runtime\Python.Runtime.dll',
        '_internal\webview\lib\Microsoft.Web.WebView2.Core.dll',
        '_internal\webview\lib\Microsoft.Web.WebView2.WinForms.dll',
        '_internal\webview\lib\runtimes\win-x64\native\WebView2Loader.dll'
    )
    $Inventory = @()
    foreach ($Relative in $Required) {
        $Path = Join-Path $Distribution $Relative
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            throw "Missing packaged dependency: $Relative. Rebuild the complete onedir before packaging."
        }
        $Item = Get-Item -LiteralPath $Path
        $Inventory += [ordered]@{
            path = $Relative.Replace('\', '/')
            sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
            bytes = $Item.Length
            fileVersion = if ($Item.Extension -eq '.dll') { [string]$Item.VersionInfo.FileVersion } else { $null }
        }
    }
    # NumPy wheels patch the MSVC C++ DLL name. Record the exact wheel filename.
    $NumpyDir = Join-Path $Distribution '_internal\numpy.libs'
    $CppRuntime = @(Get-ChildItem -LiteralPath $NumpyDir -Filter 'msvcp140*.dll' -File -ErrorAction SilentlyContinue)
    if ($CppRuntime.Count -eq 0) { throw 'Missing packaged NumPy MSVC C++ runtime. Rebuild the complete onedir.' }
    foreach ($Item in $CppRuntime) {
        $Inventory += [ordered]@{
            path = '_internal/numpy.libs/' + $Item.Name
            sha256 = (Get-FileHash -LiteralPath $Item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            bytes = $Item.Length
            fileVersion = [string]$Item.VersionInfo.FileVersion
        }
    }
    return $Inventory
}
