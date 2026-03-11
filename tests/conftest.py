"""Shared test configuration & fixtures.

Force JSON storage backend for all tests – the existing test suite was
designed around JSON-file persistence and should not hit the SQLite path.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # noqa: E402 – must precede any pyplot import

import numpy as np
import pytest

# ── environment -----------------------------------------------------------
os.environ.setdefault("ELECTROCHEM_V6_STORAGE", "json")

# ── path setup (importable from every test module) -------------------------
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for _p in (str(ROOT), str(SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ── synthetic-data helpers -------------------------------------------------

def _write_tsv(path: Path, rows: list[tuple[float, float]]) -> Path:
    """Write a two-column TSV file and return *path*."""
    lines = [f"{v:.6f}\t{i:.10f}" for v, i in rows]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def make_cv_rows(n_half: int = 60) -> list[tuple[float, float]]:
    """Two full CV cycles with oxidation / reduction peaks."""
    rows: list[tuple[float, float]] = []
    for _cycle in range(2):
        for k in range(n_half):
            v = k * 1.0 / n_half
            i = 0.001 * np.exp(-((v - 0.5) ** 2) / 0.02) + 1e-5 * v
            rows.append((v, float(i)))
        for k in range(n_half):
            v = 1.0 - k * 1.0 / n_half
            i = -0.0008 * np.exp(-((v - 0.4) ** 2) / 0.02) - 1e-5 * v
            rows.append((v, float(i)))
    return rows


def make_lsv_rows(n: int = 50) -> list[tuple[float, float]]:
    """Exponential I-V curve typical of an LSV experiment."""
    return [(0.0 + k * 0.03, float(1e-6 * np.exp(5.0 * k * 0.03))) for k in range(n)]


def make_ecsa_rows(
    scan_rate_Vs: float,
    Ev: float = 0.10,
    n_half: int = 40,
    area_cm2: float = 1.0,
    cdl_mFcm2: float = 0.020,
) -> list[tuple[float, float]]:
    """Synthetic double-layer charging CV for ECSA analysis.

    Generates two CV cycles whose anodic / cathodic currents at *Ev* produce
    a predictable ΔJ ≈ 2 · Cdl · v  (mA / cm²).
    """
    half_dI = cdl_mFcm2 * scan_rate_Vs * area_cm2 / 1000.0  # in A
    rows: list[tuple[float, float]] = []
    for _cycle in range(2):
        # forward 0 → 0.2 V
        for k in range(n_half):
            v = k * 0.2 / n_half
            i = half_dI + 1e-7 * v          # constant charging + tiny slope
            rows.append((v, float(i)))
        # backward 0.2 → 0 V
        for k in range(n_half):
            v = 0.2 - k * 0.2 / n_half
            i = -half_dI - 1e-7 * v
            rows.append((v, float(i)))
    return rows


# ── reusable fixtures ------------------------------------------------------

@pytest.fixture()
def tmp_data_dir(tmp_path: Path) -> Path:
    """Return *tmp_path* directly — a thin alias so every test starts from a
    known-clean temporary directory."""
    return tmp_path
