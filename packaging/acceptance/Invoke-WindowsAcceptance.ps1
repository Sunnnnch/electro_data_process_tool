param(
    [string]$ManifestPath = '',
    [switch]$PreflightOnly,
    [switch]$Execute,
    [string]$Confirmation = '',
    [switch]$AllowUnsignedCandidate
)

# Windows PowerShell 5.1 only; no Python, package manager, registry writes,
# forced process termination, or directory cleanup is performed by this script.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:AppIdKey = 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{F0BB4C2E-6A85-4BB4-B2FE-4D7D56600101}_is1'

function Get-ElectroChemRegistrations {
    $found = @()
    foreach ($hive in @([Microsoft.Win32.RegistryHive]::LocalMachine, [Microsoft.Win32.RegistryHive]::CurrentUser)) {
        foreach ($view in @([Microsoft.Win32.RegistryView]::Registry32, [Microsoft.Win32.RegistryView]::Registry64)) {
            $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey($hive, $view)
            try {
                $key = $base.OpenSubKey($script:AppIdKey, $false)
                if ($key) {
                    try { $found += [pscustomobject]@{ hive = [string]$hive; view = [string]$view; location = [string]$key.GetValue('InstallLocation'); version = [string]$key.GetValue('DisplayVersion') } }
                    finally { $key.Dispose() }
                }
            } finally { $base.Dispose() }
        }
    }
    return $found
}

function Get-AcceptanceMachine {
    $computer = Get-CimInstance Win32_ComputerSystem
    $product = Get-CimInstance Win32_ComputerSystemProduct
    $os = Get-CimInstance Win32_OperatingSystem
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    $tools = @()
    foreach ($name in @('python', 'python3', 'py', 'git', 'node', 'dotnet', 'code')) {
        foreach ($command in @(Get-Command $name -CommandType Application -ErrorAction SilentlyContinue)) {
            # Fresh Windows can include App Execution Alias stubs without Python.
            if ($command.Source -notmatch '\\Microsoft\\WindowsApps\\python(?:3)?\.exe$') { $tools += $command.Source }
        }
    }
    $repo = $false
    $parent = [IO.DirectoryInfo]::new($PSScriptRoot)
    while ($parent) {
        if ((Test-Path -LiteralPath (Join-Path $parent.FullName '.git')) -or (Test-Path -LiteralPath (Join-Path $parent.FullName 'src\electrochem_v6'))) { $repo = $true; break }
        $parent = $parent.Parent
    }
    $overrides = @(Get-ChildItem Env: | Where-Object { $_.Name -like 'ELECTROCHEM*' -or $_.Name -like 'WEBVIEW2*' } | Select-Object -ExpandProperty Name)
    return [pscustomobject]@{
        computerName = $env:COMPUTERNAME; vmUuid = [string]$product.UUID
        manufacturer = [string]$computer.Manufacturer; model = [string]$computer.Model
        build = [int]$os.BuildNumber; caption = [string]$os.Caption; is64Bit = [Environment]::Is64BitOperatingSystem
        is64BitProcess = [Environment]::Is64BitProcess; processorArchitecture = $env:PROCESSOR_ARCHITECTURE
        administrator = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
        developmentTools = $tools; inRepository = $repo
        codexProfilePresent = Test-Path -LiteralPath (Join-Path $env:USERPROFILE '.codex')
        dataProfilePresent = Test-Path -LiteralPath (Join-Path $env:USERPROFILE '.electrochem')
        registrations = @(Get-ElectroChemRegistrations)
        runningApplications = @(Get-Process -Name 'ElectroChem', 'ElectroChemV6', 'ElectroChem-MCP' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
        environmentOverrides = $overrides
    }
}

function Get-AcceptanceBlockers {
    param($Plan, $Machine)
    $blocked = [Collections.Generic.List[string]]::new()
    if (-not $Plan) { $blocked.Add('manifest_required'); return $blocked.ToArray() }
    if ($Plan.schemaVersion -ne 1 -or $Plan.runId -notmatch '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') { $blocked.Add('invalid_manifest_identity') }
    if ($Plan.vmUuid -notmatch '^[0-9A-Fa-f-]{36}$' -or $Plan.vmUuid -match '^0+-0+-0+-0+-0+$' -or $Plan.vmUuid -ne $Machine.vmUuid) { $blocked.Add('vm_uuid_mismatch') }
    if ($Plan.computerName -ne $Machine.computerName) { $blocked.Add('computer_name_mismatch') }
    if (($Machine.manufacturer + ' ' + $Machine.model) -notmatch '(?i)virtual machine|vmware|virtualbox|qemu|kvm|parallels') { $blocked.Add('not_a_recognized_disposable_vm') }
    if (-not $Machine.is64Bit -or -not $Machine.is64BitProcess -or $Machine.processorArchitecture -ne 'AMD64') { $blocked.Add('requires_x64_windows_and_powershell') }
    if (($Plan.osFamily -eq 'Windows10' -and $Machine.build -ne 19045) -or ($Plan.osFamily -eq 'Windows11' -and $Machine.build -lt 22000) -or $Plan.osFamily -notin @('Windows10', 'Windows11') -or $Machine.caption -match 'Server') { $blocked.Add('unexpected_windows_version') }
    if (-not $Machine.administrator) { $blocked.Add('requires_vm_administrator') }
    if ($Machine.inRepository -or $Machine.codexProfilePresent -or @($Machine.developmentTools).Count) { $blocked.Add('development_machine_or_tools_detected') }
    if ($Machine.dataProfilePresent) { $blocked.Add('existing_user_data_must_not_be_touched') }
    if (@($Machine.registrations).Count) { $blocked.Add('existing_installation_must_not_be_touched') }
    if (@($Machine.runningApplications).Count) { $blocked.Add('existing_application_must_not_be_touched') }
    if (@($Machine.environmentOverrides).Count) { $blocked.Add('remove_test_environment_overrides_in_vm') }
    if ($Plan.scenario -notin @('install_uninstall', 'repair', 'upgrade')) { $blocked.Add('invalid_scenario') }
    if ($Plan.target.version -notmatch '^\d+\.\d+\.\d+$') { $blocked.Add('invalid_target_version') }
    if ($Plan.baseline) {
        if ($Plan.scenario -ne 'upgrade' -or $Plan.baseline.version -notmatch '^\d+\.\d+\.\d+$' -or [version]$Plan.baseline.version -ge [version]$Plan.target.version) { $blocked.Add('upgrade_requires_a_genuinely_older_version') }
    }
    return $blocked.ToArray()
}

function Assert-NoReparsePath {
    param([string]$Path)
    $current = [IO.Path]::GetFullPath($Path)
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            if ((Get-Item -LiteralPath $current -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse-point paths are not allowed.' }
        }
        $parent = [IO.Path]::GetDirectoryName($current.TrimEnd('\'))
        if ($parent -eq $current) { break }
        $current = $parent
    }
}

function Read-AcceptanceArtifact {
    param($Spec, [string]$BundleDirectory, [bool]$UnsignedAllowed)
    $path = if ([IO.Path]::IsPathRooted($Spec.path)) { [IO.Path]::GetFullPath($Spec.path) } else { [IO.Path]::GetFullPath((Join-Path $BundleDirectory $Spec.path)) }
    Assert-NoReparsePath $path
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'Installer file is missing.' }
    if ($Spec.sha256 -notmatch '^[a-fA-F0-9]{64}$' -or (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $Spec.sha256) { throw 'Installer SHA-256 mismatch.' }
    $item = Get-Item -LiteralPath $path
    if ($item.VersionInfo.ProductVersion.Trim() -ne $Spec.version) { throw 'Installer PE version differs from the manifest.' }
    if ($Spec.executableName -notin @('ElectroChem.exe', 'ElectroChemV6.exe')) { throw 'Unsupported installed executable name.' }
    $signature = Get-AuthenticodeSignature -LiteralPath $path
    $unsigned = [string]$signature.Status -eq 'NotSigned'
    if ($unsigned -and -not $UnsignedAllowed) { throw 'Unsigned candidate requires explicit -AllowUnsignedCandidate.' }
    if (-not $unsigned) {
        if ([string]$signature.Status -ne 'Valid' -or -not $Spec.signerThumbprint -or $signature.SignerCertificate.Thumbprint -ne $Spec.signerThumbprint) { throw 'Invalid signature or unexpected publisher certificate.' }
    }
    return [pscustomobject]@{ path = $path; filename = $item.Name; version = $Spec.version; executableName = $Spec.executableName; sha256 = $Spec.sha256.ToLowerInvariant(); signature = [string]$signature.Status; signer = if ($unsigned) { $null } else { $signature.SignerCertificate.Thumbprint }; unsigned = $unsigned }
}

function Wait-AcceptanceCondition {
    param([scriptblock]$Condition, [int]$Seconds, [string]$Failure)
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    do {
        $value = & $Condition
        if ($value) { return $value }
        Start-Sleep -Milliseconds 300
    } while ([DateTime]::UtcNow -lt $deadline)
    throw $Failure
}

function Write-AcceptanceReport {
    [IO.File]::WriteAllText($script:ReportPath, ($script:Report | ConvertTo-Json -Depth 15), [Text.UTF8Encoding]::new($false))
}

function Add-AcceptancePass {
    param([string]$Name, $Evidence)
    $script:Report.steps += [ordered]@{ name = $Name; status = 'passed'; evidence = $Evidence; time = [DateTime]::UtcNow.ToString('o') }
    Write-AcceptanceReport
}

function Invoke-AcceptanceInstaller {
    param($Artifact, [string]$Stage)
    Assert-NoReparsePath $script:InstallDir
    # Recheck the immutable candidate immediately before executing it.
    if ((Get-FileHash -LiteralPath $Artifact.path -Algorithm SHA256).Hash -ne $Artifact.sha256) { throw 'Installer changed after preflight.' }
    $log = Join-Path $script:RunRoot ($Stage + '-setup.log')
    $arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', '/TASKS=', ('/DIR="' + $script:InstallDir + '"'), ('/LOG="' + $log + '"'))
    $process = Start-Process -FilePath $Artifact.path -ArgumentList $arguments -PassThru -WindowStyle Hidden
    if (-not $process.WaitForExit(900000)) { throw 'Installer timed out; left running for inspection. No later upgrade or uninstall will run.' }
    $process.Refresh()
    if ($process.ExitCode -ne 0) { throw "Installer exited with $($process.ExitCode); inspect $log. No automatic reboot or repair." }
    $exe = Join-Path $script:InstallDir $Artifact.executableName
    $binaries = @(Read-AcceptanceInstalledBinary $exe $Artifact)
    $mcp = Join-Path $script:InstallDir 'ElectroChem-MCP.exe'
    if ([version]$Artifact.version -ge [version]'7.0.0' -or (Test-Path -LiteralPath $mcp)) { $binaries += Read-AcceptanceInstalledBinary $mcp $Artifact }
    $registrations = @(Get-ElectroChemRegistrations)
    if (-not $registrations.Count -or @($registrations | Where-Object { $_.location.TrimEnd('\') -ne $script:InstallDir -or $_.version -ne $Artifact.version }).Count) { throw 'Installer registration is outside this acceptance directory or has the wrong version.' }
    Add-AcceptancePass $Stage @{ version = $Artifact.version; log = $log; registrations = $registrations; binaries = $binaries; mcp = if (Test-Path -LiteralPath $mcp) { 'verified' } else { 'not_available_in_pre_7_baseline' } }
    return $exe
}

function Read-AcceptanceInstalledBinary {
    param([string]$Path, $Artifact)
    Assert-NoReparsePath $Path
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf) -or (Get-Item -LiteralPath $Path).VersionInfo.ProductVersion.Trim() -ne $Artifact.version) { throw 'Installed executable is missing or its PE version did not match.' }
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    $signer = if ($signature.SignerCertificate) { $signature.SignerCertificate.Thumbprint } else { $null }
    if ($Artifact.unsigned) {
        if ([string]$signature.Status -ne 'NotSigned') { throw 'Unsigned candidate has an unexpected installed executable signature.' }
    } elseif ([string]$signature.Status -ne 'Valid' -or $signer -ne $Artifact.signer) {
        throw 'Installed executable signature is invalid or differs from the candidate publisher.'
    }
    return [ordered]@{ path = $Path; version = $Artifact.version; sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash; signature = [string]$signature.Status; signer = $signer }
}

function Test-AcceptanceListenerOwner {
    param([string]$Url, [int]$ProcessId)
    if ($Url -notmatch '^http://127\.0\.0\.1:[0-9]{4,5}$' -or $ProcessId -le 0) { return $false }
    $port = ([Uri]$Url).Port
    $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop | Where-Object { $_.LocalAddress -in @('127.0.0.1', '0.0.0.0', '::', '::1') })
    return ($listeners.Count -gt 0 -and @($listeners | Where-Object OwningProcess -ne $ProcessId).Count -eq 0)
}

function Invoke-AcceptanceApi {
    param([string]$Route, $Body = $null)
    if ($Route -notmatch '^/api/v1/(projects(?:/[A-Za-z0-9_-]+/samples)?|process/(?:preflight|jobs(?:/[A-Za-z0-9_-]+)?)|history(?:/[A-Za-z0-9_%.-]+|\?project=[A-Za-z0-9_-]+&limit=100))$') { throw 'Acceptance API route is not allowed.' }
    if (-not $script:OwnedProcess -or $script:OwnedProcess.HasExited -or -not (Test-AcceptanceListenerOwner $script:Service.url $script:OwnedProcess.Id)) { throw 'Local API listener does not belong exclusively to the owned test process. No API request was sent.' }
    $parameters = @{ Uri = $script:Service.url + $Route; Headers = @{ 'X-Electrochem-Session' = $script:Service.session_token; Origin = $script:Service.url }; TimeoutSec = 30; ErrorAction = 'Stop' }
    if ($null -ne $Body) { $parameters.Method = 'POST'; $parameters.ContentType = 'application/json; charset=utf-8'; $parameters.Body = [Text.Encoding]::UTF8.GetBytes(($Body | ConvertTo-Json -Depth 10 -Compress)) }
    return Invoke-RestMethod @parameters
}

function Get-AcceptanceNativeWindow {
    param([int]$ProcessId)
    if (-not ('ElectroChemAcceptanceWindow' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class ElectroChemAcceptanceWindow {
    delegate bool Callback(IntPtr window, IntPtr argument);
    [DllImport("user32.dll")] static extern bool EnumWindows(Callback callback, IntPtr argument);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr window, StringBuilder text, int maximum);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr window, uint message, IntPtr wParam, IntPtr lParam);
    public static IntPtr Find(int processId) {
        IntPtr found = IntPtr.Zero;
        EnumWindows(delegate(IntPtr window, IntPtr argument) {
            uint owner; GetWindowThreadProcessId(window, out owner);
            if (owner == processId) {
                var text = new StringBuilder(512); GetWindowText(window, text, text.Capacity);
                if (text.ToString().StartsWith("ElectroChem", StringComparison.Ordinal)) { found = window; return false; }
            }
            return true;
        }, IntPtr.Zero);
        return found;
    }
}
'@
    }
    return [ElectroChemAcceptanceWindow]::Find($ProcessId)
}

function Start-AcceptanceApp {
    param([string]$Executable, [string]$Stage, [bool]$CheckDiagnostics)
    if ($CheckDiagnostics) {
        $path = Join-Path $script:RunRoot ($Stage + '-environment.json')
        $check = Start-Process -FilePath $Executable -ArgumentList @('--environment-check', '--json', '--output', ('"' + $path + '"')) -PassThru -WindowStyle Hidden
        if (-not $check.WaitForExit(60000)) { throw 'Diagnostic command did not finish; inspect the VM and stop this run.' }
        $check.Refresh()
        if ($check.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $path)) { throw 'Installed environment diagnostics failed.' }
        $diagnostic = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $diagnostic.can_start -or -not $diagnostic.can_use_embedded_window -or $diagnostic.data_dir.TrimEnd('\') -ne $script:DataDir -or $diagnostic.data_mode -ne 'user') { throw 'Diagnostic environment or default installed data path is incorrect.' }
        Add-AcceptancePass ($Stage + '_environment') @{ report = $path; webview2 = $diagnostic.webview2_version }
    }
    $started = [DateTime]::UtcNow
    # This is the actual interactive client, intentionally visible for VM observation.
    $null = Start-Process -FilePath $Executable -PassThru -WindowStyle Normal
    $script:OwnedProcess = Wait-AcceptanceCondition -Seconds 120 -Failure 'The owned desktop did not publish a ready service.' -Condition {
        $path = Join-Path $script:DataDir 'desktop-service.json'
        if (-not (Test-Path -LiteralPath $path)) { return $false }
        try {
            $service = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($service.url -notmatch '^http://127\.0\.0\.1:[0-9]{4,5}$' -or $service.session_token -notmatch '^[A-Za-z0-9_-]{20,}$') { return $false }
            $owned = Get-Process -Id $service.pid -ErrorAction Stop
            if ($owned.Path -ne $Executable -or $owned.StartTime.ToUniversalTime() -lt $started.AddSeconds(-2)) { return $false }
            # A receipt alone cannot establish socket ownership on Windows,
            # where a different existing listener can share a reused port.
            if (-not (Test-AcceptanceListenerOwner $service.url $owned.Id)) { return $false }
            $owned.Refresh()
            if ((Get-AcceptanceNativeWindow $owned.Id) -eq [IntPtr]::Zero) { return $false }
            $script:Service = $service
            return $owned
        } catch { return $false }
    }
    $null = Invoke-AcceptanceApi '/api/v1/projects'
    Add-AcceptancePass ($Stage + '_desktop') @{ pid = $script:OwnedProcess.Id; executable = $Executable; nativeWindow = $true }
}

function Stop-AcceptanceApp {
    param([string]$Stage)
    $jobs = Invoke-AcceptanceApi '/api/v1/process/jobs'
    if (@($jobs.jobs | Where-Object { $_.status -in @('queued', 'running') }).Count) { throw 'Tasks still active. Refusing to close or uninstall.' }
    $script:OwnedProcess.Refresh()
    if ($script:OwnedProcess.HasExited) { throw 'The owned process exited unexpectedly.' }
    # Enumerate this PID's titled client window: MainWindowHandle may select a
    # splash or helper window. WM_CLOSE is a request, never proof of process exit.
    $window = Get-AcceptanceNativeWindow $script:OwnedProcess.Id
    if ($window -eq [IntPtr]::Zero -or -not [ElectroChemAcceptanceWindow]::PostMessage($window, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)) { throw 'No owned client window accepted WM_CLOSE. Exit via the tray manually; no later mutation will run.' }
    if (-not $script:OwnedProcess.WaitForExit(120000)) { throw 'Desktop did not exit safely. Exit via the VM tray; upgrade/uninstall has been stopped. No process was killed.' }
    $null = Wait-AcceptanceCondition -Seconds 20 -Failure 'Owned service discovery remained after desktop exit.' -Condition { -not (Test-Path -LiteralPath (Join-Path $script:DataDir 'desktop-service.json')) }
    $script:OwnedProcess = $null
    $script:Service = $null
    Add-AcceptancePass ($Stage + '_exit') @{ method = 'owned_window_WM_CLOSE'; processExited = $true; discoveryRemoved = $true }
}

function New-AcceptanceProject {
    $inputs = Join-Path $script:DataDir 'acceptance synthetic 中文 inputs'
    $null = New-Item -ItemType Directory -Path $inputs
    $file = Join-Path $inputs 'CV_acceptance.txt'
    $rows = [Collections.Generic.List[string]]::new()
    $culture = [Globalization.CultureInfo]::InvariantCulture
    foreach ($cycle in 1..2) {
        foreach ($k in 0..59) { $v = $k / 60.0; $i = 0.001 * [Math]::Exp(-[Math]::Pow($v - 0.5, 2) / 0.02) + 0.00001 * $v; $rows.Add($v.ToString('G17', $culture) + "`t" + $i.ToString('G17', $culture)) }
        foreach ($k in 0..59) { $v = 1.0 - $k / 60.0; $i = -0.0008 * [Math]::Exp(-[Math]::Pow($v - 0.4, 2) / 0.02) - 0.00001 * $v; $rows.Add($v.ToString('G17', $culture) + "`t" + $i.ToString('G17', $culture)) }
    }
    [IO.File]::WriteAllLines($file, $rows, [Text.UTF8Encoding]::new($false))
    $project = (Invoke-AcceptanceApi '/api/v1/projects' @{ name = 'Windows VM acceptance ' + $script:Report.runId; description = 'Synthetic fixture, not scientific validation.' }).project
    $payload = @{ folder_path = $inputs; input_files = @(@{ path = $file; data_type = 'CV' }); data_types = @('CV'); project_id = $project.id; params = @{ cv_match = 'prefix'; cv_prefix = 'CV'; cv_quality_check = $false } }
    $preflight = Invoke-AcceptanceApi '/api/v1/process/preflight' $payload
    if ($preflight.status -ne 'success') { throw 'Synthetic CV preflight failed.' }
    $submitted = Invoke-AcceptanceApi '/api/v1/process/jobs' $payload
    $job = Wait-AcceptanceCondition -Seconds 180 -Failure 'Synthetic CV task did not complete.' -Condition {
        $item = (Invoke-AcceptanceApi ('/api/v1/process/jobs/' + $submitted.job_id)).job
        if ($item.status -in @('failed', 'cancelled')) { throw 'Synthetic CV task failed or was cancelled.' }
        if ($item.status -eq 'succeeded') { return $item }
        return $false
    }
    $outputs = @(Get-ChildItem -LiteralPath $inputs -Recurse -File | Where-Object { $_.Extension -in @('.png', '.csv') })
    if (-not @($outputs | Where-Object Extension -eq '.png').Count -or -not @($outputs | Where-Object Extension -eq '.csv').Count) { throw 'Synthetic task did not produce PNG and CSV outputs.' }
    $script:ProjectId = $project.id
    $script:HistorySnapshot = Get-AcceptanceHistorySnapshot $script:ProjectId
    $script:Preserved = @($file) + @($outputs | Select-Object -ExpandProperty FullName)
    Add-AcceptancePass 'synthetic_cv_project' @{ projectId = $project.id; jobId = $job.job_id; historySnapshot = $script:HistorySnapshot; outputFiles = @($outputs | Select-Object -ExpandProperty FullName); inputSha256 = (Get-FileHash -LiteralPath $file).Hash }
}

function Get-AcceptanceHistorySnapshot {
    param([string]$ProjectId)
    $samples = @((Invoke-AcceptanceApi ('/api/v1/projects/' + $ProjectId + '/samples')).samples)
    $history = Invoke-AcceptanceApi ('/api/v1/history?project=' + $ProjectId + '&limit=100')
    $records = @($history.records)
    # This fixture creates exactly one CV result. A LEFT JOIN sample shell or
    # a partial result set must never count as restored history.
    if ($records.Count -ne 1 -or @($samples | Where-Object { $_.data_count -gt 0 -and 'CV' -in $_.data_types }).Count -ne 1) { throw 'The synthetic CV history record or its populated sample is missing.' }
    $key = [string]$records[0].record_key
    if (-not $key) { throw 'Synthetic history record identity is missing.' }
    $record = (Invoke-AcceptanceApi ('/api/v1/history/' + [Uri]::EscapeDataString($key))).record
    $results = $record.results | ConvertTo-Json -Depth 15 -Compress
    if ($record.record_key -ne $key -or $record.project_id -ne $ProjectId -or $record.type -ne 'CV' -or -not $results -or $results -in @('{}', 'null') -or -not @($record.output_files).Count) { throw 'Synthetic history detail lost its result metadata or outputs.' }
    $dataCount = 0
    foreach ($sample in $samples) { $dataCount += [int]$sample.data_count }
    if ($dataCount -ne $records.Count) { throw 'Project sample counts differ from the real CV history.' }
    return [ordered]@{ recordKey = $key; type = $record.type; projectId = $record.project_id; sampleName = $record.sample_name; filePath = $record.file_path; resultsJson = $results; outputFiles = @($record.output_files | Sort-Object); dataCount = $dataCount }
}

function Assert-AcceptanceHistorySnapshot {
    param($Expected, [string]$ProjectId)
    $actual = Get-AcceptanceHistorySnapshot $ProjectId
    if (($actual | ConvertTo-Json -Depth 15 -Compress) -cne ($Expected | ConvertTo-Json -Depth 15 -Compress)) { throw 'Saved CV record identity, type, result metadata, or output references changed during upgrade.' }
}

function Get-AcceptanceHashes {
    param([string[]]$Paths)
    $result = @{}
    foreach ($path in $Paths) { Assert-NoReparsePath $path; $result[$path] = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash }
    return $result
}

function Assert-AcceptanceHashes {
    param($Hashes)
    foreach ($path in $Hashes.Keys) { if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $Hashes[$path]) { throw "Preserved data changed or disappeared: $path" } }
}

function Invoke-WindowsAcceptance {
    $plan = $null
    $blocked = @()
    try { $machine = Get-AcceptanceMachine } catch { return [ordered]@{ status = 'blocked'; blockers = @('cannot_inspect_windows_machine'); message = $_.Exception.Message; installationAttempted = $false } }
    if ($ManifestPath) { try { $plan = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $blocked += 'cannot_read_manifest' } }
    try { $blocked += @(Get-AcceptanceBlockers $plan $machine) } catch { $blocked += 'incomplete_manifest' }
    $target = $null; $baseline = $null
    if ($plan) {
        try {
            $bundle = Split-Path -Parent (Resolve-Path -LiteralPath $ManifestPath).ProviderPath
            $target = Read-AcceptanceArtifact $plan.target $bundle ([bool]$AllowUnsignedCandidate)
            if ($plan.baseline) { $baseline = Read-AcceptanceArtifact $plan.baseline $bundle ([bool]$AllowUnsignedCandidate) }
        } catch { $blocked += 'artifact_verification_failed: ' + $_.Exception.Message }
    }
    $preflight = [ordered]@{ schemaVersion = 1; status = if ($blocked.Count) { 'blocked' } else { 'ready_for_explicit_vm_execution' }; blockers = $blocked; machine = $machine; installationAttempted = $false }
    if (-not $Execute -or $PreflightOnly) { return $preflight }
    if ($blocked.Count) { return $preflight }
    if ($Confirmation -cne ('DISPOSABLE-VM:' + $plan.vmUuid)) { $preflight.status = 'blocked'; $preflight.blockers = @('explicit_disposable_vm_confirmation_required'); return $preflight }
    $script:RunRoot = 'C:\ElectroChem-Acceptance\' + $plan.runId
    $script:InstallDir = Join-Path $script:RunRoot 'app'
    $script:DataDir = Join-Path $env:USERPROFILE '.electrochem\v6'
    Assert-NoReparsePath $script:RunRoot
    Assert-NoReparsePath $script:DataDir
    if (Test-Path -LiteralPath $script:RunRoot) { throw 'Run directory already exists. Restore the VM snapshot and use a fresh runId; no cleanup is automated.' }
    $null = New-Item -Path $script:RunRoot -ItemType Directory
    $script:ReportPath = Join-Path $script:RunRoot 'report.json'
    $unsigned = $target.unsigned -or ($baseline -and $baseline.unsigned)
    $script:Report = [ordered]@{
        schemaVersion = 1; runId = $plan.runId; status = 'running'; startedAt = [DateTime]::UtcNow.ToString('o'); machine = $machine
        distributionStatus = if ($unsigned) { 'unsigned_candidate' } else { 'signed_candidate' }; formalReleaseEligible = $false
        scope = 'One explicit disposable VM installation lifecycle; other acceptance matrix rows remain not_run.'
        scenario = $plan.scenario; installationAttempted = $true; target = $target; baseline = $baseline; installDirectory = $script:InstallDir; dataDirectory = $script:DataDir
        upgradeStatus = 'not_run'; repairStatus = 'not_run'; steps = @(); manualMatrixStatus = 'not_run'; ownedProcessLeftForInspection = $null
    }
    Write-AcceptanceReport
    try {
        $initial = if ($baseline) { $baseline } else { $target }
        $exe = Invoke-AcceptanceInstaller $initial 'initial_install'
        Start-AcceptanceApp $exe 'initial' (-not [bool]$baseline)
        New-AcceptanceProject
        $marker = Join-Path $script:DataDir 'acceptance-preserve-marker.txt'
        [IO.File]::WriteAllText($marker, $plan.runId, [Text.UTF8Encoding]::new($false))
        $legacy = Join-Path $script:InstallDir 'user_data'
        $null = New-Item -Path $legacy -ItemType Directory
        $legacyMarker = Join-Path $legacy 'acceptance-preserve-marker.txt'
        [IO.File]::WriteAllText($legacyMarker, $plan.runId, [Text.UTF8Encoding]::new($false))
        $script:Preserved += @($marker, $legacyMarker)
        Stop-AcceptanceApp 'initial'
        $preserved = Get-AcceptanceHashes $script:Preserved
        if ($baseline -or $plan.scenario -eq 'repair') {
            $stage = if ($baseline) { 'upgrade' } else { 'same_version_repair' }
            $exe = Invoke-AcceptanceInstaller $target $stage
            Start-AcceptanceApp $exe $stage $true
            if (-not @((Invoke-AcceptanceApi '/api/v1/projects').projects | Where-Object id -eq $script:ProjectId).Count -or -not @((Invoke-AcceptanceApi ('/api/v1/projects/' + $script:ProjectId + '/samples')).samples).Count) { throw 'The saved project or its results were not restored.' }
            Assert-AcceptanceHistorySnapshot $script:HistorySnapshot $script:ProjectId
            Assert-AcceptanceHashes $preserved
            Stop-AcceptanceApp $stage
            if ($baseline) { $script:Report.upgradeStatus = 'passed'; $script:Report.baselineProof = @{ version = $baseline.version; sha256 = $baseline.sha256 } } else { $script:Report.repairStatus = 'passed' }
            Add-AcceptancePass ($stage + '_preserves_project_and_files') @{ projectId = $script:ProjectId; preservedFileCount = $preserved.Count }
        }
        $database = Join-Path $script:DataDir 'electrochem_v6.db'
        if (-not (Test-Path -LiteralPath $database -PathType Leaf)) { throw 'Expected saved project database was not found.' }
        $preserved = Get-AcceptanceHashes ($script:Preserved + @($database))
        if (@(Get-Process -Name 'ElectroChem', 'ElectroChemV6', 'ElectroChem-MCP' -ErrorAction SilentlyContinue).Count) { throw 'A desktop or companion is still running. Uninstall will not be attempted.' }
        $registrations = @(Get-ElectroChemRegistrations)
        if (-not $registrations.Count -or @($registrations | Where-Object { $_.location.TrimEnd('\') -ne $script:InstallDir }).Count) { throw 'Uninstall registration does not belong to this test installation.' }
        $uninstaller = Join-Path $script:InstallDir 'unins000.exe'
        Assert-NoReparsePath $uninstaller
        $uninstallHash = (Get-FileHash -LiteralPath $uninstaller -Algorithm SHA256).Hash
        $uninstallSignature = Get-AuthenticodeSignature -LiteralPath $uninstaller
        $uninstallSigner = if ($uninstallSignature.SignerCertificate) { $uninstallSignature.SignerCertificate.Thumbprint } else { $null }
        if ($target.unsigned) {
            if ([string]$uninstallSignature.Status -ne 'NotSigned') { throw 'Unsigned candidate has an unexpected uninstaller signature. Inspect it before any uninstall.' }
        } elseif ([string]$uninstallSignature.Status -ne 'Valid' -or $uninstallSigner -ne $target.signer) {
            throw 'Uninstaller signature is invalid or differs from the candidate publisher.'
        }
        $uninstallLog = Join-Path $script:RunRoot 'uninstall.log'
        $process = Start-Process -FilePath $uninstaller -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', ('/LOG="' + $uninstallLog + '"')) -PassThru -WindowStyle Hidden
        if (-not $process.WaitForExit(180000)) { throw 'Uninstaller timed out; left running for inspection.' }
        $process.Refresh()
        if ($process.ExitCode -ne 0) { throw 'Uninstaller did not complete successfully.' }
        $null = Wait-AcceptanceCondition -Seconds 30 -Failure 'Uninstall did not remove this installation registration and executable.' -Condition { -not @(Get-ElectroChemRegistrations).Count -and -not (Test-Path -LiteralPath $exe) }
        Assert-AcceptanceHashes $preserved
        Add-AcceptancePass 'uninstall_preserves_data' @{ preservedHashes = $preserved; uninstallerSha256 = $uninstallHash; uninstallerSignature = [string]$uninstallSignature.Status; uninstallerSigner = $uninstallSigner; log = $uninstallLog }
        $script:Report.status = 'passed'
    } catch {
        $script:Report.status = 'failed'; $script:Report.error = $_.Exception.Message
        if (Get-Variable OwnedProcess -Scope Script -ErrorAction SilentlyContinue) { if ($script:OwnedProcess -and -not $script:OwnedProcess.HasExited) { $script:Report.ownedProcessLeftForInspection = $script:OwnedProcess.Id } }
    } finally {
        $script:Report.completedAt = [DateTime]::UtcNow.ToString('o')
        Write-AcceptanceReport
    }
    return $script:Report
}

if ($MyInvocation.InvocationName -ne '.') {
    Invoke-WindowsAcceptance | ConvertTo-Json -Depth 15
}
