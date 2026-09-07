# Windows packaging guide

ElectroChem — Intelligent Electrochemical Data Processing Software（智能电化学数据处理软件）uses a Windows desktop shell with an embedded WebView2 UI and a local HTTP service. The service binds to loopback; ordinary desktop use does not require a Python installation on the destination PC.

## Build environment

Build on Windows x64 with Python **3.12**. `build_onedir.ps1` creates `packaging/.venv-pack`, checks the Python version even when reusing it, pins pip 25.3, and installs `requirements-pack.txt`. Runtime direct dependencies come from `requirements-frozen.txt`; PyInstaller is 6.17.0, pywebview remains 4.4.1, pystray is 0.19.5, and the official MCP SDK is pinned to 1.30.0. This deliberately uses the maintained SDK 1.x API (`mcp>=1.30,<2`), not the incompatible 2.x API. The SDK supports Python 3.10+ for source installations; the Windows build remains 3.12. Transitive versions are recorded in each artifact's `runtime-requirements.txt`; the direct baseline is not a hash-locked complete dependency graph.

```powershell
.\packaging\build_onedir.ps1
# Optional explicit Python 3.12 executable:
.\packaging\build_onedir.ps1 -PythonPath 'C:\Python312\python.exe'

.\packaging\build_installer.ps1 -IsccPath 'D:\build-tools\Inno Setup 6\ISCC.exe'

# Preserve an existing portable distribution and its data at the original path:
.\packaging\build_onedir.ps1 -OutputRoot dist_mcp_theme
.\packaging\build_installer.ps1 -SourceRoot dist_mcp_theme -OutputRoot dist_installer_mcp_theme
```

`ELECTROCHEM_ISCC_PATH` can supply the compiler path instead. Default Inno Setup 6 installation paths and PATH are also checked. A compiler extracted into the workspace is supported; installing Inno system-wide is not required. Obtain it from the [official Inno Setup site](https://jrsoftware.org/isinfo.php).

By default the onedir build cleans only `build/ElectroChemV6` and `dist/ElectroChem`. Use a new `-OutputRoot` to preserve an existing portable distribution and its data without moving them. Installer `-SourceRoot` selects that distribution; installer `-OutputRoot` selects its artifact directory. These root arguments accept only repository top-level names `dist` or `dist_<name>`, never absolute paths, path separators, or parent traversal. The installer build removes only the exact installer and checksum for the requested version. `build_paths.ps1` verifies the full path against its expected repository location, rejects reparse points, and refuses cleanup if an output contains portable `user_data`. Other build directories are preserved, including an older `dist/ElectroChemV6` folder. Do not replace these guards with a broad recursive deletion of `build` or `dist`.

The version is read from `src/electrochem_v6/config.py`, or supplied with `-AppVersion`; no source file is rewritten. Outputs are `dist/ElectroChem/ElectroChem.exe`, the console companion `dist/ElectroChem/ElectroChem-MCP.exe`, and `dist_installer/ElectroChem-Setup-<version>.exe` plus its `.sha256` file. Published portable archives are named `ElectroChem-<version>-win64.zip`. Both executables share the onedir dependencies; keep the complete folder together.

`windows_version.py` supplies the executable's Windows ProductName/FileDescription from `APP_NAME` and stores the numeric version separately. User-visible names do not append V6. The installer/uninstaller and shortcuts use the same product name, and both new shortcuts carry `AppUserModelID=ElectroChem.Desktop`. The spec includes the desktop PNG/ICO resources and the matching packaging icon.

## Installed and portable modes

- The onedir/ZIP build contains `portable.marker`. Its default application data lives in `user_data` beside the executable. Keep this whole directory together on a writable disk.
- The Inno installer excludes both source markers, removes only an existing target `portable.marker`, and creates `installed.marker`. Installed mode defaults to `%USERPROFILE%\.electrochem\v6`, regardless of whether the installation directory is writable.
- With neither marker, the same user directory is the default. Two markers together are an error. `ELECTROCHEM_V6_DATA_DIR`, when explicitly set, overrides the default.
- Existing `user_data` is never deleted during installation, upgrade, or uninstall. The desktop migration flow copies reviewed application data; older result records can still reference the original directories, so preserve them until those references have been checked.

Keep the existing installation directory `{autopf}\ElectroChemV6` and AppId `{F0BB4C2E-6A85-4BB4-B2FE-4D7D56600101}` unchanged for upgrade compatibility. The new installer points its shortcuts to `ElectroChem.exe` and removes only the superseded `{app}\ElectroChemV6.exe` plus the two exact shortcuts under the previous Chinese display name. It does not delete `user_data`, reset settings, or migrate data automatically. A taskbar pin or custom shortcut pointing to the old executable may need to be unpinned and recreated from the new shortcut; Setup does not modify user-managed pins.

The desktop and each MCP companion hold `Local\ElectroChemV6.Desktop` while running. Setup and uninstall ask the user to finish or cancel processing, exit the client including its tray icon, and disconnect the ElectroChem connection in their MCP host. `CloseApplications=no` and `RestartApplications=no` prevent installer-driven task termination or restart. Data-directory single-instance locking is separate from this installation mutex; the companion does not acquire the data lock.

## WebView2 prerequisite

Setup checks the Evergreen Runtime `pv` registry value in the 32-bit machine/current-user views. Having the ordinary Microsoft Edge browser installed is not equivalent to having the WebView2 Runtime. See [Microsoft's distribution guidance](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution).

The default installer **does not bundle or download WebView2**. If it is missing, Setup offers to open Microsoft's download page and waits for the user to install the Evergreen Runtime. Silent installation fails with an actionable message when the prerequisite is missing.

An offline release can explicitly embed the Microsoft Evergreen Standalone x64 installer:

```powershell
.\packaging\build_installer.ps1 `
  -IsccPath 'D:\build-tools\Inno Setup 6\ISCC.exe' `
  -WebView2OfflineInstaller 'D:\prerequisites\MicrosoftEdgeWebView2RuntimeInstallerX64.exe'
```

The build rejects an invalid signature or a signer other than Microsoft Corporation. At setup time, when the Runtime is absent, the user must approve running the bundled prerequisite; its installation result and the Runtime registry entry are checked. A required restart stops application installation until Windows is restarted. Passing this option is the only way the prerequisite is bundled; document that fact with the distributed artifact.

## Signing and release checks

Local test artifacts may be unsigned and emit a warning. Official Windows releases require an existing publisher certificate; do not describe an unsigned local build as a signed release.

```powershell
$env:ELECTROCHEM_SIGN_CERT_SHA1 = 'CERTIFICATE_THUMBPRINT'
$env:ELECTROCHEM_TIMESTAMP_URL = 'http://timestamp.digicert.com' # optional
.\packaging\build_installer.ps1 -RequireSigning -IsccPath 'D:\build-tools\Inno Setup 6\ISCC.exe'
```

The existing `sign_windows_binary.ps1` signs and verifies the desktop executable, MCP companion, and installer using Authenticode. Official releases sign both executables before creating the ZIP, require `WINDOWS_SIGNING_CERT_BASE64` and its certificate password, publish SHA-256 files for installer and ZIP, and refuse to release without verified signatures. Preparing or pushing source does not require a signing certificate; publishing official Windows binaries does.

## Publish an explicitly reviewed version

Source pushes run CI only. CI tests Python 3.10 and 3.12, installs Chromium, requires browser tests, and imports the official MCP SDK before running the complete suite. It never calculates a semantic-release version, rewrites `APP_VERSION`, creates a release commit, or publishes binaries.

The **Release (Manual)** workflow requires two explicit inputs: an existing stable `tag` such as `v7.0.1`, and `expected_commit`, the full 40-character SHA of the reviewed release commit. There is no empty-input or latest-tag fallback. Its tag, checked-out commit, and `APP_VERSION` must agree, and tracked sources must remain unchanged. The release's exact changelog section must exist; `7.0.10` or `7.0.1-rc.1` cannot substitute for `7.0.1`.

Prepare the source version and changelog on a review branch first. After that branch is reviewed and its intended changes are integrated, explicitly publish the chosen tag on the intended commit. A source update, a tag push, and publication of signed binaries are separate actions. Do not create or move tags as a side effect of a version calculation, and do not force-update an existing public tag.

Once repository authentication, the source/tag, and the publisher signing secrets are ready, select **Actions → Release (Manual) → Run workflow** on the branch containing the updated workflow. Enter the exact tag and commit. The equivalent GitHub CLI invocation is:

```powershell
# Replace this placeholder with the full reviewed commit SHA before running.
gh workflow run release.yml --ref main -f tag=v7.0.1 -f expected_commit=FULL_REVIEWED_COMMIT_SHA
```

The manual workflow repeats browser and real MCP stdio tests, builds from that exact commit, signs both portable executables, and builds the signed installer. Before uploading, `release_validation.py` checks both artifact names and SHA-256 files, the versions/product identities of the GUI, MCP companion and installer, valid Authenticode signatures from the same publisher certificate, and the remote tag's current commit. It also checks that the ZIP includes the complete portable application and excludes user data. Published assets are the ZIP, installer, and their two `.sha256` files.

An already public release is rejected before building and again before uploading. The workflow can resume an unpublished draft or create a new release; it does not replace an existing public download set. If a release is already public, prepare a new version for subsequent changes. If signing credentials are absent or invalid, source preparation and CI can still succeed, but the binary release stops.

For read-only verification of locally prepared, signed artifacts:

```powershell
.\packaging\publish_release_refs.ps1 `
  -Tag v7.0.1 -ExpectedCommit FULL_REVIEWED_COMMIT_SHA `
  -PortableZip .\dist\ElectroChem-7.0.1-win64.zip `
  -Installer .\dist_installer\ElectroChem-Setup-7.0.1.exe `
  -VerifyOnly -VerifyRemoteTag
```

This command requires the local tag and checked-out source to match the supplied commit. The signed-artifact gate intentionally rejects unsigned local test builds. Without `-VerifyOnly`, the script additionally requires an explicit `-TargetBranch`; it atomically pushes only that branch at `ExpectedCommit` and the named tag. It never chooses `main` or another branch automatically. The manual GitHub workflow uses `-VerifyOnly` and does not push source refs.

## Local MCP connection

Open the desktop first, then configure the MCP host to launch the companion with an absolute path. The companion connects to that desktop's local HTTP service; it does not create a second GUI, processing engine, or database writer. Default access is read-only.

```json
{
  "mcpServers": {
    "electrochem": {
      "command": "C:\\Program Files\\ElectroChemV6\\ElectroChem-MCP.exe",
      "args": []
    }
  }
}
```

Adjust `command` to the actual installed/portable location. The desktop's copyable configuration is preferable when its data directory is customized. `--data-dir <path>` selects that desktop's data directory; otherwise the companion uses the same environment/marker/user-directory rules as the GUI. `--url http://127.0.0.1:<port>` explicitly selects a loopback HTTP endpoint; the client validates its identity. Add `--allow-write` only when the host should expose tools that submit processing and write result files. It does not grant arbitrary shell execution or general file deletion.

Source users can run `python run_v6.py mcp`, `python -m electrochem_v6.mcp_cli`, or `electrochem-mcp` after installing the Python package. Every entry accepts `--help`, `--data-dir`, `--url`, and `--allow-write`. Missing/stale desktop discovery is reported to the host; start or reopen the selected desktop instead of copying session tokens. The desktop writes `desktop-service.json` for this connection. `desktop-instance.json` is separate activation IPC and is not an HTTP endpoint.

MCP stdio must carry protocol messages only: diagnostics go to stderr. The GUI executable uses PyInstaller's windowed bootloader, whose stdin/stdout/stderr can be unavailable, so do not configure the host to launch `ElectroChem.exe --mcp`. The spec builds the companion with `console=True`, includes the SDK metadata and runtime-selected AnyIO backend, and collects its dependencies beside the GUI. See the [official MCP SDK](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x) and [PyInstaller stdio guidance](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#sys-stdin-sys-stdout-and-sys-stderr-in-noconsole-windowed-applications-windows-only).

Before distributing, exercise the **built companion** through real redirected stdin/stdout: initialize, list tools, invoke a read-only tool, submit a small job with explicit write access, verify UTF-8 paths and data-directory discovery, then close stdin. Confirm there is no font/setup/banner text on stdout, no GUI spawned by the companion, and no hidden processing process left behind. Exit the MCP host's connection before replacing or uninstalling its executable.

The desktop's **Check for updates** action only reads metadata from `Sunnnnch/electro_data_process_tool` on GitHub after a user click. Stable clients exclude prereleases. The result requires a Windows installer and matching checksum; the current filename is preferred while previously published `ElectroChemV6-Setup-<version>.exe` assets remain recognizable. The download action opens the fixed official Releases page. This is not an Authenticode verification of the remote file; verify the downloaded installer signature and checksum before installation. No installer is downloaded or launched by the updater.

## Validation before distribution

Run the packaging/update tests, then exercise the built executable on a separate Windows test account or VM. Check first launch, WebView2 missing/present, tray reopening, exit while processing, second launch, installed/portable data selection, an upgrade with old user data, and uninstall retaining data. Test an offline-prerequisite artifact separately if producing one. A successful PyInstaller/Inno compile alone does not validate installation or the target machine's prerequisites.

For an immediate startup failure, inspect the application data directory's logs; the packaged executable has no console. Check that the complete onedir folder, static UI resources, and native runtime dependencies were copied. Rebuild from the dedicated environment after a dependency change. Some Windows systems may need the Microsoft Visual C++ x64 Runtime for scientific packages.
