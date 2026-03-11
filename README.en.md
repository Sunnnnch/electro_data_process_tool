# ElectroChem V6

[![CI](https://github.com/Sunnnnch/electro_data_process_tool/actions/workflows/ci.yml/badge.svg)](https://github.com/Sunnnnch/electro_data_process_tool/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/Sunnnnch/electro_data_process_tool?include_prereleases)](https://github.com/Sunnnnch/electro_data_process_tool/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[中文](README.md) | [English](README.en.md)

A local electrochemical data processing and analysis toolkit for batch `LSV`, `CV`, `EIS`, and `ECSA` workflows, with a local Web UI, project/history management, and optional AI-assisted analysis.

## Overview

`ElectroChem V6` consolidates common electrochemical data-processing workflows into a single workspace, reducing repetitive manual exports, scattered scripts, and fragmented result tracking.

Typical use cases:

- Batch-process multiple experimental samples
- Generate unified outputs for `LSV`, `CV`, `EIS`, and `ECSA`
- Keep projects, histories, and quality reports for later review
- Use a local Web UI instead of manual script execution

## Features

- Supports `LSV`, `CV`, `EIS`, and `ECSA` processing
- Supports batch file matching by prefix, contains, or regex
- Supports `LSV` target-current interpolation, potential conversion, `iR` compensation, `Tafel`, `Onset`, and `Halfwave`
- Supports `LSV` Tafel fit R² validation (warns in quality report when R² < 0.99)
- Supports `CV` peak detection, `ΔEp` calculation, and charge integration
- Supports `EIS` `Nyquist` / `Bode` plots and **Randles equivalent circuit fitting** (Rs + Rct‖Cdl)
- Supports `ECSA`, `Cdl`, and `RF` calculation with built-in material Cs presets (Pt, Carbon, IrO₂, RuO₂, etc.)
- Supports reference electrode presets (Ag/AgCl, SCE, Hg/HgO, Hg/Hg₂SO₄, MSE, RHE)
- Skip-on-error mode: individual file failures do not abort the batch, errors are summarized in results
- Per-file progress feedback (N/M files processed) during LSV/CV/EIS processing
- UI supports basic/advanced mode toggle to simplify operation for beginners
- Includes project management, history tracking (filterable by metric range and data type), quality summaries, and quality reports
- Supports project result ZIP export (`GET /api/v1/projects/{id}/export-zip`)
- Includes a local HTTP service and Web UI
- Includes optional LLM / Agent integration

## Quick Start

### Windows

1. Double-click `setup.bat`
2. After installation, double-click `start.bat`

Default UI:

- `http://127.0.0.1:8010/ui`

### Command Line

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

### `LSV`

- Target-current interpolation
- `Tafel` fitting
- `iR` compensation
- Overpotential calculation
- `Onset` / `Halfwave`
- Configurable quality-check toggle and thresholds

### `CV`

- Curve plotting
- Peak detection (optional)
- `ΔEp` peak potential separation (requires peak detection enabled)
- Charge integration (`∫|I|dE`)
- Configurable quality-check toggle and thresholds

### `EIS`

- `Nyquist` plot
- `Bode` plot (magnitude + phase)
- **Randles equivalent circuit fitting** (simplified Rs + Rct‖Cdl model, auto-annotated on Nyquist plot)
- History persistence and result export

### `ECSA`

- `ΔJ-v` fitting
- `Cdl`
- `ECSA`
- `RF`
- Built-in material Cs presets (Pt=20, Carbon=20, IrO₂=40, RuO₂=35, NiFeOOH=60, MnO₂=40, CoOₓ=50 µF/cm²)
- `RF`

## Quality Checks

Quality checking currently focuses on `LSV` and `CV`. After processing, the app can generate quality summaries and, when needed, full quality reports.

Current configurable coverage:

- `LSV`: enable/disable quality checking and tune thresholds for minimum points, outlier ratio, scan span, noise, jump ratio, and local fluctuation
- `CV`: enable/disable quality checking and tune thresholds for minimum points and cycle-closure tolerance

Implementation:

- `src/electrochem_v6/core/processing_quality.py`
- `src/electrochem_v6/core/processing_lsv.py`
- `src/electrochem_v6/core/processing_cv.py`

## Outputs

Typical outputs include:

- Per-type plots
- `LSV_results.csv`
- `ECSA_results.csv`
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

Run:

```powershell
setup.bat
```

### Where are logs and data stored

Default: `~/.electrochem/v6/`. Override with environment variables (see below).

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ELECTROCHEM_V6_DATA_DIR` | Shared data root (other paths follow automatically) | `~/.electrochem/v6` |
| `ELECTROCHEM_V6_PORT` | HTTP server port | `8010` |
| `ELECTROCHEM_V6_LOG_FILE` | Log file path | `<data_dir>/logs/v6_server.log` |
| `ELECTROCHEM_V6_LOG_LEVEL` | Log verbosity: `DEBUG` / `INFO` / `WARNING` / `ERROR` | `INFO` |
| `ELECTROCHEM_V6_PROJECTS_FILE` | Projects list file | `<data_dir>/projects.json` |
| `ELECTROCHEM_V6_HISTORY_FILE` | Processing history file | `<data_dir>/processing_history.json` |
| `ELECTROCHEM_V6_CONVERSATION_FILE` | Chat history file | `<data_dir>/conversation_history.json` |
| `ELECTROCHEM_V6_TEMPLATE_FILE` | Processing templates file | `<data_dir>/process_templates.json` |
| `ELECTROCHEM_V6_QUALITY_REPORT_FILE` | Quality report file | `latest_quality_report.json` |
| `ELECTROCHEM_V6_LLM_CONFIG_FILE` | LLM config file | `~/.electrochem/llm_config.json` |
| `ELECTROCHEM_V6_STORAGE` | Storage backend: `sqlite` (default) or `json` | `sqlite` |
| `OPENAI_API_KEY` | OpenAI API key (takes priority over config file) | — |
| `DEEPSEEK_API_KEY` | DeepSeek API key | — |
| `QWEN_API_KEY` | Qwen API key | — |
| `KIMI_API_KEY` | Kimi API key | — |

> **Security note**: The server binds to `127.0.0.1` only (localhost). No CORS or authentication is needed.

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

- `src/electrochem_v6/core/processing_core_v6.py`: compatibility entrypoint, shared utilities, and unified exports
- `src/electrochem_v6/core/processing_pipeline.py`: batch orchestration and directory scanning
- `src/electrochem_v6/core/processing_quality.py`: quality checks and reports
- `src/electrochem_v6/core/processing_lsv.py`: `LSV` processing and `IR/Tafel` logic
- `src/electrochem_v6/core/processing_cv.py`: `CV` processing
- `src/electrochem_v6/core/processing_eis.py`: `EIS` processing
- `src/electrochem_v6/core/processing_ecsa.py`: `ECSA` processing and sample-matching helpers

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
```

Current validation status:

- `110 passed, 1 skipped`
- `python run_v6.py check` passed
- `python run_v6.py smoke --port 8011` passed

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

- Add finer quality checks for `EIS` / `ECSA`
- Add screenshots or workflow diagrams to the README
- Validate the `PyInstaller` packaging pipeline end-to-end
- `EIS` Randles fitting with CPE instead of Cdl for a more general model
- `CV` multi-cycle auto-segmentation and cyclic voltammetry parameter extraction
- Display skipped-error file details in the frontend result view
