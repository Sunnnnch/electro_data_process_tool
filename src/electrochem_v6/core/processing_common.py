"""Shared processing helpers with no domain-specific calculations."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, Mapping, ParamSpec, TypeVar

_PlotParams = ParamSpec("_PlotParams")
_PlotResult = TypeVar("_PlotResult")
_MATPLOTLIB_LOCK = threading.RLock()


@dataclass(frozen=True)
class ProcessingFileContext:
    """Resolved paths and names for one input file."""

    subfolder: str
    filename: str
    filepath: str
    sample_name: str
    file_stem: str
    output_dir: str


def serialized_plotting(
    function: Callable[_PlotParams, _PlotResult],
) -> Callable[_PlotParams, _PlotResult]:
    """Serialize pyplot-based rendering that relies on global figure state.

    The HTTP server handles requests on worker threads, while pyplot keeps the
    current figure and ``rcParams`` at process scope.  Keeping the lock around
    the complete rendering function prevents one run from saving or closing a
    figure owned by another run.
    """

    @wraps(function)
    def wrapped(*args: _PlotParams.args, **kwargs: _PlotParams.kwargs) -> _PlotResult:
        with _MATPLOTLIB_LOCK:
            return function(*args, **kwargs)

    return wrapped


def ensure_output_dir(output_dir: Any, fallback_dir: str) -> str:
    """Return a usable output directory and create it when needed."""
    resolved = str(output_dir or fallback_dir)
    os.makedirs(resolved, exist_ok=True)
    return resolved


def build_file_context(
    subfolder: str,
    filename: str,
    params: Mapping[str, Any] | None = None,
) -> ProcessingFileContext:
    """Resolve standard file-processing path fields used by core modules."""
    params = params or {}
    filepath = os.path.join(subfolder, filename)
    sample_name = os.path.basename(subfolder)
    file_stem = os.path.splitext(os.path.basename(filename))[0]
    output_dir = ensure_output_dir(params.get("output_dir"), subfolder)
    return ProcessingFileContext(
        subfolder=subfolder,
        filename=filename,
        filepath=filepath,
        sample_name=sample_name,
        file_stem=file_stem,
        output_dir=output_dir,
    )


def apply_plot_font(pyplot: Any, font_name: str) -> None:
    """Apply the standard font settings to a matplotlib pyplot-like module."""
    pyplot.rcParams["font.sans-serif"] = [font_name]
    pyplot.rcParams["axes.unicode_minus"] = False


def save_current_figure(
    pyplot: Any,
    image_path: str,
    *,
    dpi: int = 300,
    bbox_inches: str = "tight",
    close: bool = True,
) -> str:
    """Save the current pyplot figure, creating the parent directory first."""
    parent = os.path.dirname(image_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    try:
        pyplot.savefig(image_path, dpi=dpi, bbox_inches=bbox_inches)
    finally:
        if close:
            pyplot.close()
    return image_path


def format_sample_title(template: str, sample_name: str, **values: Any) -> str:
    """Format a plot title with the common ``{sample}`` token."""
    payload = {"sample": sample_name, **values}
    try:
        return str(template).format(**payload)
    except Exception:
        return str(template).replace("{sample}", sample_name)


__all__ = [
    "ProcessingFileContext",
    "apply_plot_font",
    "build_file_context",
    "ensure_output_dir",
    "format_sample_title",
    "save_current_figure",
    "serialized_plotting",
]
