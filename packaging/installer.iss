#define AppName "智能电化学数据处理软件"
#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif
#define AppPublisher "Sun"
#define AppExeName "ElectroChem.exe"
#ifndef AppSourceDir
  #define AppSourceDir "..\dist\ElectroChem"
#endif

[Setup]
AppId={{F0BB4C2E-6A85-4BB4-B2FE-4D7D56600101}
AppName={#AppName}
AppVerName={#AppName}
AppVersion={#AppVersion}
VersionInfoDescription={#AppName}
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\ElectroChemV6
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist_installer
#ifdef WebView2OfflineInstaller
OutputBaseFilename=ElectroChem-Setup-{#AppVersion}-offline
#else
OutputBaseFilename=ElectroChem-Setup-{#AppVersion}
#endif
Compression=lzma
SolidCompression=yes
WizardStyle=modern
SetupIconFile=assets\app_icon.ico
MinVersion=10.0.19045
ArchitecturesInstallIn64BitMode=x64os
ArchitecturesAllowed=x64os
AppMutex=Local\ElectroChemV6.Desktop
CloseApplications=no
RestartApplications=no
#ifdef PublisherSigning
SignTool=electrochem_publisher
SignedUninstaller=yes
#else
SignedUninstaller=no
#endif

[Languages]
Name: "default"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"

[Messages]
SetupAppRunningError=ElectroChem is still running. Wait for processing to finish, or cancel it in the application, then choose Exit from the tray menu and disconnect the ElectroChem MCP connection in your AI host before continuing.%n%nSetup will not force-stop processing tasks.
UninstallAppRunningError=ElectroChem is still running. Finish or cancel processing, then choose Exit from the tray menu and disconnect the ElectroChem MCP connection before uninstalling.

[Files]
Source: "{#AppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "user_data\*,portable.marker,installed.marker"
#ifdef WebView2OfflineInstaller
#ifndef WebView2OfflineSHA256
  #error Supply the SHA-256 of the verified Microsoft WebView2 offline installer.
#endif
Source: "{#WebView2OfflineInstaller}"; DestName: "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"; Flags: dontcopy
#endif

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; AppUserModelID: "ElectroChem.Desktop"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon; AppUserModelID: "ElectroChem.Desktop"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent

[InstallDelete]
; Remove only exact legacy shortcuts and the superseded executable.
; Preserve the installation, portable user_data, and application identity.
Type: files; Name: "{autoprograms}\电化学数据处理软件.lnk"
Type: files; Name: "{autodesktop}\电化学数据处理软件.lnk"
Type: files; Name: "{app}\ElectroChemV6.exe"

[UninstallDelete]
Type: files; Name: "{app}\installed.marker"

[Code]
const
  WebView2Key = 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WebView2DownloadPage = 'https://developer.microsoft.com/en-us/microsoft-edge/webview2/#download-section';
  MinimumWebView2Major = 120;

function HasRuntimeAt(RootKey: Integer): Boolean;
var
  Version: String;
  PackedVersion: Int64;
begin
  Result := RegQueryStringValue(RootKey, WebView2Key, 'pv', Version);
  if Result then begin
    Result := StrToVersion(Trim(Version), PackedVersion);
    if Result then
      Result := ComparePackedVersion(PackedVersion, PackVersionComponents(MinimumWebView2Major, 0, 0, 0)) >= 0;
  end;
end;

function HasWebView2: Boolean;
begin
  { Microsoft documents pv in the 32-bit machine and current-user views. }
  Result := HasRuntimeAt(HKLM32) or HasRuntimeAt(HKCU32);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';
  if CheckForMutexes('Local\ElectroChemV6.Desktop') then begin
    Result := 'ElectroChem is running. Finish or cancel processing, exit from the tray menu, and disconnect the ElectroChem MCP connection in your AI host. Setup does not stop your tasks.';
    Exit;
  end;
  if not IsDotNetInstalled(net462, 0) then begin
    Result := 'Microsoft .NET Framework 4.6.2 or later is required for the desktop window. Windows 10 22H2 and Windows 11 normally include a compatible version. Repair the Windows .NET Framework component, then retry Setup. Setup does not download or modify this Windows component.';
    Exit;
  end;
  if HasWebView2 then Exit;
#ifdef WebView2OfflineInstaller
  if WizardSilent then begin
    Result := 'WebView2 Runtime 120 or later is missing or outdated. Run Setup interactively to approve the included Microsoft offline installer, or install/upgrade WebView2 first.';
    Exit;
  end;
  if MsgBox('Microsoft Edge WebView2 Runtime 120 or later is required. Install or upgrade it now using the included, Microsoft-signed offline installer?', mbConfirmation, MB_YESNO) <> IDYES then begin
    Result := 'Install or upgrade Microsoft Edge WebView2 Runtime to version 120 or later before continuing.';
    Exit;
  end;
  ExtractTemporaryFile('MicrosoftEdgeWebView2RuntimeInstallerX64.exe');
  if CompareText(GetSHA256OfFile(ExpandConstant('{tmp}\MicrosoftEdgeWebView2RuntimeInstallerX64.exe')), '{#WebView2OfflineSHA256}') <> 0 then begin
    Result := 'The included WebView2 installer failed its integrity check. Obtain a fresh ElectroChem installer and retry.';
    Exit;
  end;
  if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebView2RuntimeInstallerX64.exe'), '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then begin
    Result := 'Unable to start the Microsoft WebView2 installer. Install the Runtime manually and retry.';
    Exit;
  end;
  if ResultCode = 3010 then begin
    NeedsRestart := True;
    Result := 'Microsoft WebView2 installation requires a restart. Restart Windows, then run ElectroChem Setup again.';
    Exit;
  end;
  if (ResultCode <> 0) or not HasWebView2 then
    Result := 'Microsoft WebView2 Runtime could not be verified after installation. Complete its installation, then retry.';
#else
  Result := 'Microsoft Edge WebView2 Runtime 120 or later is missing or outdated. This standard installer does not bundle it. Install or upgrade the Evergreen Runtime from Microsoft, or use the ElectroChem offline installer, then retry Setup.';
  if not WizardSilent then
    if MsgBox(Result + #13#10#13#10 + 'Open the official Microsoft download page?', mbConfirmation, MB_YESNO) = IDYES then
      ShellExec('open', WebView2DownloadPage, '', '', SW_SHOWNORMAL, ewNoWait, ResultCode);
#endif
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  PortableMarker: String;
begin
  if CurStep = ssPostInstall then begin
    { Exact marker cleanup only; preserve every legacy user_data file. }
    PortableMarker := ExpandConstant('{app}\portable.marker');
    if FileExists(PortableMarker) then
      if not DeleteFile(PortableMarker) then
        RaiseException('Unable to remove portable.marker. Installation mode would be ambiguous.');
    if not SaveStringToFile(ExpandConstant('{app}\installed.marker'), 'installed-v1' + #13#10, False) then
      RaiseException('Unable to write installed.marker.');
  end;
end;
