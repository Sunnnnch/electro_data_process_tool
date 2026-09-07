# ElectroChem application icon

The approved artwork is **D · Intelligent Data**, selected on 2026-09-08:
`design/icon-concepts/2026-09-08/D-intelligent-data.png`.

- `app_icon.png` is a byte-for-byte copy of the selected PNG. Its shape, colors,
  transparency, and full canvas are preserved.
- `app_icon.ico` contains 32-bit PNG frames at 16, 20, 24, 32, 40, 48, 64, 128,
  and 256 pixels. Only resizing and format conversion are applied.
- `packaging/assets/app_icon.ico` is the same ICO used for the executable and
  installer. `ui/static/app_icon.png` is the same original PNG for the web icon.
- Desktop code uses `electrochem_v6.desktop.branding.icon_path()` to locate these
  package resources in source and frozen applications. Windows identity is
  `ElectroChem.Desktop`; the visible product name is ElectroChem.

To reproduce the resources on Windows, run from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File packaging/build_icon.ps1
```

The script uses .NET `System.Drawing`, verifies every ICO size with the Windows
icon decoder, and checks the matching PNG/ICO copies using SHA-256. It does not
regenerate the design or edit the original artwork.
