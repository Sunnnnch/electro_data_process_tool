# ElectroChem V6

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
- Supports `CV` peak detection
- Supports `EIS` `Nyquist` and `Bode` plots
- Supports `ECSA`, `Cdl`, and `RF` calculation
- Includes project management, history tracking, quality summaries, and quality reports
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
- Peak detection
- Configurable quality-check toggle and thresholds

### `EIS`

- `Nyquist` plot
- `Bode` plot
- History persistence and result export

### `ECSA`

- `ΔJ-v` fitting
- `Cdl`
- `ECSA`
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

You can control paths via environment variables:

- `ELECTROCHEM_V6_DATA_DIR`
- `ELECTROCHEM_V6_LOG_FILE`
- `ELECTROCHEM_V6_PORT`

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

- `41 passed, 1 skipped`
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
