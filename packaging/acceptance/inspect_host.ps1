param(
    [Parameter(Mandatory = $true)][string]$ReportPath
)

# Read-only host inventory. Never enable Windows features, change groups,
# export keys, create/start VMs, or install software from this script.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$destination = [IO.Path]::GetFullPath($ReportPath)
if (Test-Path -LiteralPath $destination) { throw 'Choose a new report filename; existing reports are preserved.' }
if (-not (Test-Path -LiteralPath (Split-Path -Parent $destination) -PathType Container)) {
    throw 'The report parent directory must already exist.'
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
$report = [ordered]@{
    schemaVersion = 1
    generatedAt = [DateTime]::UtcNow.ToString('o')
    scope = 'Read-only host readiness; not guest installation acceptance or publisher signing'
    isAdministrator = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    windowsSandboxPresent = (Test-Path -LiteralPath "$env:SystemRoot\System32\WindowsSandbox.exe")
    hyperV = [ordered]@{ commandAvailable = [bool](Get-Command Get-VM -ErrorAction SilentlyContinue); canQuery = $false; machines = @(); error = $null }
    signing = [ordered]@{ certificates = @(); storesRead = @(); errors = @(); configuredSettings = @(); signTools = @() }
    blockers = @()
    cleanMachineAcceptanceExecuted = $false
    officialArtifactsSigned = $false
}
if ($report.hyperV.commandAvailable) {
    try {
        $report.hyperV.machines = @(Get-VM -ErrorAction Stop | Select-Object Name,State,Generation,Version)
        $report.hyperV.canQuery = $true
    } catch { $report.hyperV.error = $_.Exception.Message }
}
if (-not $report.hyperV.canQuery) {
    $report.blockers += 'This process cannot manage Hyper-V; an authorized VM administrator or a separate prepared test machine is required.'
}
foreach ($store in @('Cert:\CurrentUser\My', 'Cert:\LocalMachine\My')) {
    try {
        $report.signing.certificates += @(Get-ChildItem -LiteralPath $store -CodeSigningCert | ForEach-Object {
            [pscustomobject]@{
                store = $store; subject = $_.Subject; issuer = $_.Issuer; thumbprint = $_.Thumbprint
                notBefore = $_.NotBefore.ToUniversalTime().ToString('o'); notAfter = $_.NotAfter.ToUniversalTime().ToString('o')
                hasPrivateKey = $_.HasPrivateKey
                currentlyValid = ($_.NotBefore -le (Get-Date) -and $_.NotAfter -gt (Get-Date))
            }
        })
        $report.signing.storesRead += $store
    } catch { $report.signing.errors += "$store : $($_.Exception.GetType().Name)" }
}
foreach ($name in @('ELECTROCHEM_SIGN_CERT_SHA1', 'WINDOWS_SIGNING_CERT_BASE64', 'WINDOWS_SIGNING_CERT_PASSWORD', 'ELECTROCHEM_SIGNTOOL_PATH')) {
    # Configuration presence only: never print credentials or their values.
    $report.signing.configuredSettings += [pscustomobject]@{
        name = $name; configured = [bool][Environment]::GetEnvironmentVariable($name)
    }
}
$kitRoot = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10'
if (Test-Path -LiteralPath $kitRoot -PathType Container) {
    $report.signing.signTools = @(Get-ChildItem -LiteralPath $kitRoot -Filter signtool.exe -Recurse -File -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
}
if ($env:ELECTROCHEM_SIGNTOOL_PATH -and (Test-Path -LiteralPath $env:ELECTROCHEM_SIGNTOOL_PATH -PathType Leaf)) {
    $report.signing.signTools += (Resolve-Path -LiteralPath $env:ELECTROCHEM_SIGNTOOL_PATH).Path
}
if (-not @($report.signing.certificates | Where-Object { $_.hasPrivateKey -and $_.currentlyValid }).Count) {
    $report.blockers += 'No currently valid code-signing certificate with a private-key handle was found in the inspected personal stores. Provider enrollment or an existing external signing service is needed.'
}
if (-not $report.signing.signTools.Count) { $report.blockers += 'Windows SDK SignTool was not found in Windows Kits or the explicitly configured tool path.' }
$json = $report | ConvertTo-Json -Depth 10
$stream = [IO.File]::Open($destination, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
try {
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($json + [Environment]::NewLine)
    $stream.Write($bytes, 0, $bytes.Length)
} finally { $stream.Dispose() }
$json
