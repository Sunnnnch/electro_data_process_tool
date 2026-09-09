<h1>
  <img src="docs/logo.png" width="36" height="36" align="absmiddle" />
  ElectroChem | Intelligent Electrochemical Data Processing Software
</h1>

[![CI](https://github.com/Sunnnnch/electro_data_process_tool/actions/workflows/ci.yml/badge.svg)](https://github.com/Sunnnnch/electro_data_process_tool/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/Sunnnnch/electro_data_process_tool?include_prereleases)](https://github.com/Sunnnnch/electro_data_process_tool/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[中文](README.md) | [English](README.en.md)

Data processing · Project management · Result review · AI-assisted analysis

ElectroChem processes local electrochemical data for batch `LSV`, `CV`, `EIS`, `ECSA`, and `COUPLED/FE` workflows, with project history, reproducible reports, and optional AI-assisted analysis. Core data processing works without configuring AI.

Current source version: **7.0.1** · [Release notes and upgrade guidance](docs/release_7.0.1.md) · [Changelog](CHANGELOG.md)

Windows version 7.0.1 retains existing data locations and internal compatibility identifiers. Back up application data and original/output files, finish tasks, exit the client, and disconnect MCP clients before upgrading. Do not rename data folders merely because their names still contain `v6`. See below for macOS data locations.

[User guide](src/electrochem_v6/ui/static/help_manual.en.md) · [Synthetic CV example](src/electrochem_v6/ui/static/guide-cv-demo.csv) · [Developer API guide](docs/api_guide.en.md)

## Overview

`ElectroChem` consolidates common electrochemical data-processing workflows into a single workspace, reducing repetitive manual exports, scattered scripts, and fragmented result tracking.

Typical use cases:

- Batch-process multiple experimental samples
- Generate unified outputs for `LSV`, `CV`, `EIS`, `ECSA`, and `COUPLED`
- Keep projects, histories, and quality reports for later review
- Use a local Web UI instead of manual script execution

## Features

- Supports `LSV`, `CV`, `EIS`, `ECSA`, and `COUPLED` processing
- Supports batch file matching by prefix, contains, or regex
- Supports `LSV` target-current interpolation, potential conversion, `iR` compensation, `Tafel`, `Onset`, and `Halfwave`
- Supports `LSV` Tafel fit R² validation (warns in quality report when R² < 0.99)
- Supports `CV` peak detection, `ΔEp` calculation, and charge integration
- Supports `EIS` Nyquist/Bode plots, six equivalent circuits, frequency windows, residuals, parameter intervals, and independent KK consistency checks
- Supports `ECSA`, `Cdl`, and `RF` calculation with built-in material Cs presets (Pt, Carbon, IrO₂, RuO₂, etc.)
- Supports COUPLED/FE metrics from product quantification tables, including Faradaic efficiency and selectivity
- Supports reference electrode presets (Ag/AgCl, SCE, Hg/HgO, Hg/Hg₂SO₄, MSE, RHE) and temperature-aware Nernst conversion
- Skip-on-error mode: individual file failures do not abort the batch, errors are summarized in results
- Processing and AI requests use persistent background jobs with per-file/stage progress and cooperative cancellation. Interrupted processing can restart as a new job after preflight; AI conversations are not automatically resent
- UI supports basic/advanced mode toggle to simplify operation for beginners
- Includes a project recycle bin, restore/permanent delete, cursor-paginated history with on-demand detail, and managed-storage cleanup
- Project results, comparisons, and reports have separate views. Replay historical runs with original or edited parameters, compare two exact records, and export scoped HTML/Markdown reports. New runs retain parameters and input/dependency fingerprints; stored uploads can restore missing ZIP inputs. See the [workspace guide (Chinese)](docs/project_workspace.md).
- Search all project history by sample or file name and filter by type or date. Choose a project color from swatches or a color picker. Link an existing parameter template, preview its changes, and apply it explicitly before processing; selected data and auxiliary files are preserved.
- Supports project result ZIP export (`GET /api/v1/projects/{id}/export-zip`)
- Includes a local HTTP service and Web UI
- Includes optional LLM / Agent integration
- Assistant action cards preview parameter changes, exact comparisons, replay plans and scoped reports. LSV recommendations use the production calculation pipeline and expose candidate fit diagnostics; missing experimental conditions must be supplied.
- Save independent replicate groups with effective n, mean, sample SD, individual points and error bars. Retain chosen versions and exclusion reasons, and export CSV/SVG.
- A shared task panel lists processing and AI jobs with status filters, cancellation, failure details and links to their results or conversations.
- Appearance offers four interface styles: Modern, Paper Editorial, Soft Modules and Pixel Retro. Each supports nine preset palettes, system following and custom colors, remembers its own palette and preserves older settings on upgrade. Text size, density and the background grid remain independent; assistant reading surfaces and chart previews follow the palette while scientific exports stay on white paper. See the [appearance guide (Chinese)](docs/appearance.md).

## Quick Start

### Windows

The current Windows desktop release targets **Windows 10 22H2 / Windows 11 x64**, with **WebView2 Runtime 120+**. Python and computation dependencies are bundled. Windows ARM, 32-bit Windows and Linux desktops are not formally supported. See the [Windows desktop guide](docs/desktop_client.md) for requirements, environment diagnostics and download options.

The standard installer requires a suitable WebView2 installation. The `-offline` installer includes Microsoft's signed standalone WebView2 installer; the portable ZIP still needs WebView2 on the target PC. Basic analysis works offline; cloud AI needs network access. **Desktop → Environment check** provides refreshable checks and a copyable diagnostic report without uploading it.

- Installed application: open the “智能电化学数据处理软件” shortcut after installation.
- Source checkout: run `setup.bat` to install dependencies, then `start.bat` to launch.

`start.bat` opens the native desktop window and starts the local service automatically. Launching it again activates the existing window for the same data directory. For browser mode, use `start_browser.bat`; its default address is:

- `http://127.0.0.1:8010/ui`

The desktop client adds a system tray, task-aware exit, window and appearance persistence, native file selection and saving, and update checks. The title bar and scrollbars follow the selected theme. **Desktop → AI connection (MCP)** provides local configuration for external AI clients to query projects, preflight inputs, run calculations and export reports; see the [MCP guide](docs/mcp.md). See the [desktop guide](docs/desktop_client.md) for installation, portable mode and legacy data.

### macOS

The macOS client targets **macOS 13+**, with separate native candidates for Apple Silicon (`arm64`) and Intel (`x64`). These candidates await macOS CI validation; this does not mean a Mac download is available in the public Release. Current builds use ad-hoc signing and are not notarized by Apple.

Source users need **Python 3.12** matching their chip architecture. Run `bash Start_Mac.command` from the repository; the first launch creates `.venv-macos` and downloads dependencies. The desktop uses the system **WKWebView**, without WebView2. Data defaults to `~/Library/Application Support/ElectroChem`. Reopen background windows from the Dock; ⌘Q goes through the task-aware exit flow. See the [macOS guide (Chinese)](docs/macos_client.md) for candidate installation, diagnostics and MCP paths.

### Process your first file

1. In Data Processing, click Select Data and choose TXT/CSV files or a folder. Review the listed types and enabled files.
2. Optionally link a project and apply a parameter template. Confirm the data columns, units, electrode area, and potential reference against the experiment.
3. Run Preflight and check recognition, parameters, and auxiliary file pairing. Then click Run Processing.
4. Review metrics and quality in Processing Results. Use the project's Results, Compare, and Report views to archive, replay, and export.

For a first walkthrough, save the synthetic example above as `CV_demo.csv`. It is demonstration data, not an experiment. Its settings and expected outputs are in the [user guide](src/electrochem_v6/ui/static/help_manual.en.md); the [data generation notes](docs/demo_data.md) give the synthetic formulas and verified outputs.

### Windows Command Line

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run_v6.py --port 8010
```

## Common Commands

Most common:

```powershell
python run_v6.py --port 8010
```

Other commands:

```powershell
python run_v6.py check
python run_v6.py smoke --port 8011
python run_v6.py stress --port 8012
python run_v6.py version
```

## Endpoints

- UI: `http://127.0.0.1:8010/ui`
- Health: `http://127.0.0.1:8010/health`
- API example: `http://127.0.0.1:8010/api/v1/projects`

## Supported Data Types

### Input compatibility scope

The application directly reads exported numeric text tables with tab, comma,
semicolon, or whitespace delimiters. Columns, units, and the EIS imaginary sign
convention can be configured per processing method. Proprietary vendor project
files must first be exported to text. The repository fixtures validate generic
text layouts; they are not CH Instruments, Gamry, Autolab, BioLogic, or other
vendor certification files. See
[`docs/input_format_compatibility.md`](docs/input_format_compatibility.md).

### `LSV`

- Target-current interpolation
- `Tafel` fitting
- `iR` compensation with manual Rs, same-folder/root-fallback/recursive/specified-file EIS pairing, plus preflight and report provenance
- Overpotential calculation
- `Onset` / `Halfwave`
- Configurable quality-check toggle and thresholds

### `CV`

- Curve plotting
- Peak detection (optional)
- `ΔEp` peak potential separation (requires peak detection enabled)
- Charge integration (`Q = ∫|I|dt`, using the experimental scan rate; charge is omitted when the scan rate is missing)
- Configurable quality-check toggle and thresholds

### `EIS`

- `Nyquist` plot
- `Bode` plot (magnitude + phase)
- **Six equivalent circuits**: single-time-constant RC/CPE, semi-infinite Warburg RC/CPE, and two-time-constant RC/CPE; double branches are ordered from fast to slow
- Closed frequency windows in Hz, uniform or modulus weighting, numerical convergence, R², RMSE, approximate local 95% parameter intervals, and identifiability diagnostics
- Independent Lin-KK consistency checks; numerical thresholds and heuristic diagnostics do not establish a circuit's physical correctness, and unavailable intervals are explicitly marked
- Nyquist/Bode fit overlays, residual plots, pointwise CSV and full diagnostic JSON exports; history replay and reports preserve the model, window, weighting, and diagnostics. See [EIS fitting notes](docs/eis_fitting.md)

### `ECSA`

- `ΔJ-v` fitting
- `Cdl`
- `ECSA`
- `RF`
- Built-in material Cs presets, with the selected Cs, geometric area, formulas, and material/electrolyte limitations persisted in results

### `COUPLED / FE`

- Calculates Faradaic efficiency directly from an existing product quantification table
- Can locate raw one-dimensional signal peaks, align them to an internal standard, quantify products, and calculate FE
- Calculates mole-based product selectivity and FE-share selectivity per sample
- Supports `CSV` / `TSV` / `TXT` / `XLSX` / `XLS` product tables
- Writes `coupled_results.csv` and appends normalized metrics to `processing_results.csv`

The product table must provide at least these fields. English aliases are accepted:

```csv
sample,product,product_moles,n,charge
sample-a,H2,0.000002,2,1.0
sample-a,CO,0.000001,2,1.0
```

`product_moles` is the product amount in mol, `n` is the electron-transfer count, and `charge` is total charge in C.

Neutral column names may declare units, for example `Product Moles (mmol)`, `Charge (mC)`, `Current (mA)`, and `Time (min)`. Values are normalized to mol, C, A, and s before calculation. Columns without unit declarations retain the documented defaults. Unsupported units, conflicting declarations, and competing columns are rejected. The runtime includes xlrd for legacy `.xls` files.

ECSA requires at least two distinct valid scan rates; same-rate replicates alone cannot determine a slope. Last-N averaging uses paired forward/reverse crossings. CV cycle plots support starting inside the potential window; incomplete trailing cycles are reported and remain in the full curve.

Peak-analysis mode uses a measurement table plus a method JSON. The table links samples, signal files, and charge; the method defines the internal standard, expected product positions, quantitative nuclei, electron counts, and search/quantification windows. Auto-location, reference-shift alignment, and constrained pseudo-Voigt fitting are independently optional. A fixed relative quantification window is applied across the batch, with `fe_peak_diagnostics.csv` and `fe_peak_results.json` exported for review.

The bundled method file is a structural example only. Validate `electron_count`, `nuclei_count`, internal-standard concentration/volume, response factors, and peak windows for the actual reaction and analytical method.

## Quality Checks

Quality checking currently covers `LSV`, `CV`, and peak-based FE analysis. After processing, the app can generate quality summaries and, when needed, full quality reports.

Current configurable coverage:

- `LSV`: enable/disable quality checking and tune thresholds for minimum points, outlier ratio, scan span, noise, jump ratio, and local fluctuation
- `CV`: enable/disable quality checking and tune thresholds for minimum points and cycle-closure tolerance
- `COUPLED/FE peak analysis`: checks detection/quantification SNR, ambiguous candidates, fit R², reference shift, and total FE above 100%

Implementation:

- `src/electrochem_v6/core/processing_quality.py`
- `src/electrochem_v6/core/processing_lsv.py`
- `src/electrochem_v6/core/processing_cv.py`

## Outputs

Typical outputs include:

- Per-type plots
- `LSV_results.csv`
- `ECSA_results.csv`
- `coupled_results.csv`
- `processing_results.csv`
- `quality_report.json`
- `latest_quality_report.json`
- Project and history records

Actual outputs depend on enabled data types and selected parameters.

## FAQ

### Port already in use

Use another port:

```powershell
python run_v6.py --port 8011
```

### No virtual environment yet

On Windows, run the command below. On macOS, use `bash Start_Mac.command` as described above:

```powershell
setup.bat
```

### Where are logs and data stored

Windows installed clients default to `~/.electrochem/v6/`; portable builds use `user_data` beside the executable. The macOS desktop uses `~/Library/Application Support/ElectroChem`. Running the browser/CLI service directly from source still defaults to `~/.electrochem/v6/`. Override the shared root with `ELECTROCHEM_V6_DATA_DIR`; writable data cannot be placed inside a macOS `.app` bundle.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ELECTROCHEM_V6_DATA_DIR` | Shared data root (other paths follow automatically) | Depends on launch mode; see above |
| `ELECTROCHEM_V6_PORT` | HTTP server port | `8010` |
| `ELECTROCHEM_V6_LOG_FILE` | Log file path | `<data_dir>/logs/v6_server.log` |
| `ELECTROCHEM_V6_LOG_LEVEL` | Log verbosity: `DEBUG` / `INFO` / `WARNING` / `ERROR` | `INFO` |
| `ELECTROCHEM_V6_PROJECTS_FILE` | Projects list file | `<data_dir>/projects.json` |
| `ELECTROCHEM_V6_HISTORY_FILE` | Processing history file | `<data_dir>/processing_history.json` |
| `ELECTROCHEM_V6_CONVERSATION_FILE` | Chat history file | `<data_dir>/conversation_history.json` |
| `ELECTROCHEM_V6_TEMPLATE_FILE` | Processing templates file | `<data_dir>/process_templates.json` |
| `ELECTROCHEM_V6_QUALITY_REPORT_FILE` | Quality report file | `latest_quality_report.json` |
| `ELECTROCHEM_V6_LLM_CONFIG_FILE` | LLM config file | `~/.electrochem/llm_config.json` |
| `OPENAI_API_KEY` | OpenAI API key (takes priority over config file) | — |
| `DEEPSEEK_API_KEY` | DeepSeek API key | — |
| `QWEN_API_KEY` | Qwen API key | — |
| `KIMI_API_KEY` | Kimi API key | — |

> **Security note**: The server binds to `127.0.0.1` only (localhost). No CORS or authentication is needed.

Projects, processing history, conversations, and templates are stored in `<data_dir>/electrochem_v6.db`. Legacy JSON files are used only for a validated, atomic first-run import. Failed validation does not set the completion marker, so import is retried at the next startup.

### Database maintenance

```powershell
# Integrity, schema, record counts, and orphan project references
python run_v6.py db-check

# Create a verified rolling backup
python run_v6.py db-backup

# Preview likely test-generated projects without changing data
python run_v6.py db-cleanup-preview

# A safety backup is created first; explicit confirmation is required
python run_v6.py db-restore "backup.db" --yes
```

At most one automatic backup is created every 24 hours. The latest five backups are kept in `<data_dir>/backups/`.

## Troubleshooting

### Unicode / Encoding errors

If you see garbled CJK text in PowerShell or CI:

```powershell
$env:PYTHONUTF8 = "1"
```

### Chinese font missing (boxes in plots)

Install a CJK font (SimHei / Microsoft YaHei / SimSun).  
You can also specify a font name via the `font` processing parameter.

### matplotlib backend error

In headless environments (CI / Docker):

```python
import matplotlib
matplotlib.use("Agg")
```

### Data file read failure

- Check encoding: UTF-8, GBK, GB2312, ASCII, Latin-1 are supported
- Check `start_line` parameter to skip header rows
- Ensure columns are separated by tabs or commas

### Debug mode

Enable verbose logging:

```powershell
$env:ELECTROCHEM_V6_LOG_LEVEL = "DEBUG"
python run_v6.py
```

## Project Structure

### Entry Points

- `run_v6.py`: command-line entrypoint
- `setup.bat`: creates virtual environment and installs dependencies
- `start.bat`: launches the local service and UI

### Core Modules

- `src/electrochem_v6/core/processing_core_v6.py`: shared logging, plotting, exceptions, and processing utilities
- `src/electrochem_v6/core/processing_scan.py`: folder scanning, filename matching, and data-start detection
- `src/electrochem_v6/core/processing_registry.py`: single source of truth for modules and parameter schemas
- `src/electrochem_v6/core/processing_module_runtime.py`: processing-module registry and runtime contract
- `src/electrochem_v6/core/processing_module_orchestrator.py`: primary modular batch orchestrator
- `src/electrochem_v6/core/processing_quality.py`: quality checks and reports
- `src/electrochem_v6/core/processing_lsv.py`: `LSV` processing and `IR/Tafel` logic
- `src/electrochem_v6/core/processing_cv.py`: `CV` processing
- `src/electrochem_v6/core/processing_eis.py`: `EIS` processing
- `src/electrochem_v6/core/processing_ecsa.py`: `ECSA` processing and sample-matching helpers
- `src/electrochem_v6/core/processing_coupled*.py`: product quantification, Faradaic efficiency, and selectivity calculation
- `src/electrochem_v6/core/processing_result_*.py`: normalized result models, collection, and export
- `src/electrochem_v6/core/processing_metric_registry.py`: metric definitions and aliases

### Other Modules

- `src/electrochem_v6/server/`: HTTP service and routes
- `src/electrochem_v6/store/`: projects, history, templates, local persistence
- `src/electrochem_v6/ui/`: local Web UI
- `src/electrochem_v6/agent/`: agent toolchain
- `src/electrochem_v6/llm/`: LLM clients and configuration

## Development and Testing

Install development dependencies:

```powershell
pip install -r requirements-dev.txt
```

Common checks:

```powershell
python run_v6.py check
python run_v6.py smoke --port 8011
python -m pytest -q
python -m pytest -q tests/test_v6_numerical_reference.py
```

Versioned electrochemical numerical references live in `tests/reference_data/`.
Changes to formulas, unit conversions, or fitting methods must run the reference
suite; expected values must be derived independently from the implementation.

## Packaging and Release

Packaging-related files are located in:

- `packaging/`

Before release, review:

- `PUBLISH_CHECKLIST.md`
- `CHANGELOG.md`
- `packaging/README.md`

## License

This project is released under the `MIT` License. See `LICENSE`.

## Roadmap

Reasonable next improvements:

- Add finite-length diffusion, inductive elements, and system-specific EIS model comparisons
- Add screenshots or workflow diagrams to the README
- Validate the `PyInstaller` packaging pipeline end-to-end
- `CV` multi-cycle auto-segmentation and cyclic voltammetry parameter extraction
- Display skipped-error file details in the frontend result view
