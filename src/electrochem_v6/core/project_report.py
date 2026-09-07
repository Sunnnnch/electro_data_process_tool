"""Project report rendering and export helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from .reproducible_report_service import (
    build_project_report_document,
    export_report_document,
    render_report_html,
    render_report_markdown,
)


def safe_project_report_name(project_name: str) -> str:
    """Return a filesystem-safe project name for exported report files."""
    clean = "".join(ch if ch not in '\\/:*?"<>|' and ord(ch) >= 32 else "_" for ch in str(project_name or "").strip())
    return clean.rstrip(". ") or "project"


def build_project_report_markdown(*, project: Mapping[str, Any], report_data: Mapping[str, Any], generated_at: str | None = None) -> str:
    return render_report_markdown(build_project_report_document(project=project, report_data=report_data, generated_at=generated_at))


def build_project_report_html(*, project: Mapping[str, Any], report_data: Mapping[str, Any], generated_at: str | None = None) -> str:
    return render_report_html(build_project_report_document(project=project, report_data=report_data, generated_at=generated_at))


def export_project_report(*, project: Mapping[str, Any], report_data: Mapping[str, Any], output_dir: str, format: str = "markdown") -> dict[str, Any]:
    project_name = str((project or {}).get("name") or "project").strip() or "project"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    document = build_project_report_document(project=project, report_data=report_data)
    return export_report_document(document, output_dir=output_dir,
                                  stem=f"{safe_project_report_name(project_name)}_project_report_{timestamp}", format=format)
