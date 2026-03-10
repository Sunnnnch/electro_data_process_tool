# V5/V6 Baseline Acceptance Checklist

This checklist freezes the minimum regression baseline for the v6 no-license refactor, while keeping v5 compatibility visible.

## Scope

- v5 CLI entry availability
- v6 runner health and smoke behavior
- v6 API route regression tests
- Optional full-repository pytest regression

## Quick Acceptance Commands

Run one-click baseline regression:

```powershell
python v6_refactor_no_license/scripts/baseline_regression.py
```

Windows shortcut:

```powershell
powershell -ExecutionPolicy Bypass -File v6_refactor_no_license/scripts/run_baseline_regression.ps1
```

Full mode (includes full `pytest -q`):

```powershell
python v6_refactor_no_license/scripts/baseline_regression.py --full
```

## Acceptance Criteria (Quick Mode)

1. `python cli_process.py --help` exits with code `0`.
2. `python v6_refactor_no_license/run_v6.py --help` exits with code `0`.
3. `python v6_refactor_no_license/run_v6.py check` exits with code `0`.
4. `python v6_refactor_no_license/run_v6.py smoke --port <free_port>` exits with code `0`.
5. `python -m pytest -q v6_refactor_no_license/tests/test_v6_server.py` exits with code `0`.

## Acceptance Criteria (Full Mode)

Quick mode criteria, plus:

1. `python -m pytest -q` exits with code `0`.

## Manual Spot Checks (GUI)

These are not fully automatable and should be manually spot-checked before release:

1. Open `http://127.0.0.1:<port>/ui`.
2. Professional tab is default.
3. Folder picker can return a path.
4. Multi-select data types can be toggled and corresponding parameter panels show/hide correctly.
5. Template load/save/delete works.
6. Processing result panel updates after run.

## Baseline Reports

Each run writes:

- `v6_refactor_no_license/reports/baseline_regression_latest.json`
- `v6_refactor_no_license/reports/baseline_regression_<timestamp>.json`

These reports can be attached to release notes or QA handoff.

