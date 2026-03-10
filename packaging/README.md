# Packaging Guide

This directory contains the first packaging scaffold for `v6`.

## Scope

Current packaging target:

1. build a Windows `onedir` application with PyInstaller
2. package a lightweight desktop launcher
3. start the local HTTP service and open the UI in the default browser
4. wrap the `onedir` output into an installer with Inno Setup

This is intentionally not a full embedded WebView shell yet. It is the lowest-risk release path for the current architecture.

## Layout

- `electrochem_v6_launcher.py`: packaged desktop launcher
- `electrochem_v6.spec`: PyInstaller `onedir` spec
- `requirements-pack.txt`: minimal packaging environment dependencies
- `build_onedir.ps1`: create venv and build `dist/ElectroChemV6`
- `build_installer.ps1`: build installer from `dist/ElectroChemV6`
- `installer.iss`: Inno Setup script
- `assets/app_icon.ico`: packaged app icon

## Recommended Workflow

1. create a dedicated packaging venv
2. build `onedir`
3. test the `dist/ElectroChemV6` directory manually
4. build the installer

## Build Commands

```powershell
cd v6_refactor_no_license/packaging
./build_onedir.ps1
./build_installer.ps1
```

## Notes

1. Do not build from the main development environment. Use the dedicated `.venv-pack`.
2. The launcher currently opens `http://127.0.0.1:<port>/ui` in the system browser.
3. Runtime data still defaults to `~/.electrochem/v6/`.
4. If later you switch to `pywebview`, keep this directory and only replace the launcher entrypoint.
