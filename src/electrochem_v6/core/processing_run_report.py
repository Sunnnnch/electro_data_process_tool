"""Backward-compatible report entry points for a processing manifest."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .reproducible_report_service import (
    build_run_report_document,
    export_report_document,
    render_report_html,
    render_report_markdown,
)


def build_run_report_markdown(manifest: Mapping[str, Any], *, generated_at: str | None = None) -> str:
    return render_report_markdown(build_run_report_document(manifest, generated_at=generated_at))


def build_run_report_html(manifest: Mapping[str, Any], *, generated_at: str | None = None) -> str:
    return render_report_html(build_run_report_document(manifest, generated_at=generated_at))


def _write(manifest: Mapping[str, Any], *, output_dir: str, filename: str, format: str) -> str:
    if Path(filename).name != filename:
        raise ValueError("report filename must be a plain local filename")
    result = export_report_document(build_run_report_document(manifest), output_dir=output_dir,
                                    stem=Path(filename).stem, format=format)
    return str(result["path"])


def write_run_report(manifest: Mapping[str, Any], *, output_dir: str, filename: str = "run_report.md") -> str:
    return _write(manifest, output_dir=output_dir, filename=filename, format="markdown")


def write_run_report_html(manifest: Mapping[str, Any], *, output_dir: str, filename: str = "run_report.html") -> str:
    return _write(manifest, output_dir=output_dir, filename=filename, format="html")
