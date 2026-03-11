import json
import math
from pathlib import Path

import electrochem_v6.core.process_service as process_service


def _write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")


def _build_lsv(path: Path, points: int, *, scale: float = 1.0) -> None:
    lines = ["Potential Current\n"]
    for i in range(points):
        pot = -0.1 + 1.2 * (i / max(points - 1, 1))
        norm = max(0.0, min(1.0, (pot + 0.1) / 1.2))
        cur_a = (0.001 + 0.16 * (norm**1.7)) * scale
        lines.append(f"{pot:.6f} {cur_a:.8f}\n")
    _write_lines(path, lines)


def _build_cv(path: Path) -> None:
    lines = ["Potential Current\n"]
    up = [-0.2 + 1.0 * (i / 119.0) for i in range(120)]
    dn = [0.8 - 1.0 * (i / 119.0) for i in range(120)]
    series = up + dn
    for pot in series:
        cur_a = 0.002 * math.sin(4.5 * pot) + 0.0008 * pot
        lines.append(f"{pot:.6f} {cur_a:.8f}\n")
    _write_lines(path, lines)


def _build_eis(path: Path) -> None:
    lines = ["Freq Zreal Zimag\n"]
    freqs = [1e5, 5e4, 2e4, 1e4, 5e3, 2e3, 1e3, 500, 200, 100, 50, 20, 10, 5, 2, 1]
    for f in freqs:
        root = (f / 100.0) ** 0.5
        z_real = 1.8 + 8.5 / (1.0 + root)
        z_imag = -4.2 / (1.0 + 0.7 * root)
        lines.append(f"{f:.6f} {z_real:.6f} {z_imag:.6f}\n")
    _write_lines(path, lines)


def _build_ecsa(path: Path, amplitude: float) -> None:
    lines = ["Potential Current\n"]
    potentials = [0.00, 0.05, 0.10, 0.15, 0.20, 0.15, 0.10, 0.05, 0.00]
    for idx, pot in enumerate(potentials):
        if idx <= 4:
            cur_a = 0.00022 + amplitude * pot
        else:
            cur_a = 0.00006 + 0.22 * amplitude * pot
        lines.append(f"{pot:.6f} {cur_a:.8f}\n")
    _write_lines(path, lines)


def test_v6_e2e_real_data_pipeline_all_types(tmp_path):
    data_dir = tmp_path / "synthetic_e2e"
    data_dir.mkdir(parents=True, exist_ok=True)

    # LSV: one good file + one intentionally short file for quality-fail branch.
    _build_lsv(data_dir / "LSV_good.txt", points=80, scale=1.0)
    _build_lsv(data_dir / "LSV_bad.txt", points=8, scale=0.8)

    # CV / EIS
    _build_cv(data_dir / "CV_demo.txt")
    _build_eis(data_dir / "EIS_demo.txt")

    # ECSA (at least two scan rates to fit DeltaJ-v line)
    _build_ecsa(data_dir / "ECSA20.txt", amplitude=0.0010)
    _build_ecsa(data_dir / "ECSA40.txt", amplitude=0.0018)
    _build_ecsa(data_dir / "ECSA60.txt", amplitude=0.0026)

    payload = {
        "folder_path": str(data_dir),
        "data_types": ["LSV", "CV", "EIS", "ECSA"],
        "params": {
            "plot_bode": True,
            "plot_nyquist": True,
            "ecsa_ev": 0.10,
            "ecsa_last_n": 1,
            "ecsa_avg_last_n": False,
            "target_current": "10,100",
        },
    }
    response = process_service.process_folder(payload)
    assert response.get("status") == "success"

    result = response.get("result") or {}
    assert result.get("data_types") == ["LSV", "CV", "EIS", "ECSA"]

    summary_path = Path(result.get("summary_path") or "")
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary.get("data_types") == ["LSV", "CV", "EIS", "ECSA"]

    quality = result.get("quality_summary") or {}
    assert quality.get("total_files", 0) >= 2
    # LSV_bad.txt should trigger a quality-fail branch (insufficient points).
    assert quality.get("failed", 0) >= 1

    output_files = [Path(p) for p in (result.get("processing", {}).get("output_files") or [])]
    assert output_files
    assert any(p.name == "summary.json" for p in output_files)
    assert any(p.name == "quality_report.json" for p in output_files)
    assert any(p.name == "LSV_results.csv" for p in output_files)
    assert any(p.name == "ECSA_results.csv" for p in output_files)

    # Verify real artifacts from each data type exist.
    assert list(data_dir.glob("*_CV.png"))
    assert list(data_dir.glob("*_EIS_Nyquist.png"))
    assert list(data_dir.glob("*_EIS_Bode.png"))
    assert list(data_dir.glob("*_LSV.png"))
    assert list(data_dir.glob("*_ECSA.png"))
