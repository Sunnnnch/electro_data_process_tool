"""Shared contracts for pluggable processing modules.

The service-level batch orchestrator executes built-in and extension modules
through this contract so detection, validation, results, and artifacts share a
single path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from electrochem_v6.core.processing_registry import ProcessingModuleSpec
from electrochem_v6.core.processing_result_models import ProcessingResult


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "item"):
        try:
            return _json_ready(value.item())
        except Exception:
            pass
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_ready(item) for item in value]
    return str(value)


@dataclass(frozen=True)
class ModuleRunContext:
    """Runtime context shared with a processing module."""

    folder_path: str
    params: Mapping[str, Any]
    project_id: str | None = None
    run_id: str | None = None
    output_dir: str | None = None


@dataclass(frozen=True)
class ModuleRunResult:
    """Normalized module output."""

    data_type: str
    results: tuple[ProcessingResult, ...] = ()
    artifacts: tuple[str, ...] = ()
    quality_reports: tuple[Mapping[str, Any], ...] = ()
    messages: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "data_type": str(self.data_type).upper(),
            "results": [item.to_dict() for item in self.results],
            "artifacts": [str(item) for item in self.artifacts if str(item).strip()],
            "quality_reports": [_json_ready(dict(item)) for item in self.quality_reports],
            "messages": [str(item) for item in self.messages if str(item).strip()],
            "metadata": _json_ready(dict(self.metadata)),
        }


@runtime_checkable
class ProcessingModule(Protocol):
    """Protocol for future processing modules."""

    spec: ProcessingModuleSpec

    def detect_files(self, context: ModuleRunContext) -> Sequence[str]:
        """Return input files this module can process."""
        ...

    def validate_params(self, context: ModuleRunContext) -> list[str]:
        """Return validation messages; empty means the module can run."""
        ...

    def run(self, context: ModuleRunContext, files: Sequence[str]) -> ModuleRunResult:
        """Run processing and return normalized output."""
        ...


__all__ = ["ModuleRunContext", "ModuleRunResult", "ProcessingModule"]
