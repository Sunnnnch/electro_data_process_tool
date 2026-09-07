"""Runtime registry for pluggable processing modules.

The static registry in :mod:`processing_registry` describes the built-in v6
processing surface.  This module adds a runtime layer for future extensions:
modules can be registered, discovered, validated, and run through one small
contract without changing the UI or service code for every new type.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from electrochem_v6.core.processing_module_contract import (
    ModuleRunContext,
    ModuleRunResult,
    ProcessingModule,
)
from electrochem_v6.core.processing_registry import (
    PROCESSING_MODULES,
    ProcessingModuleSpec,
)

MODULE_RUNTIME_SCHEMA_VERSION = "1.2"


class ModuleRegistrationError(ValueError):
    """Raised when a processing module cannot be registered."""


class ModuleRunError(RuntimeError):
    """Raised when a registered module cannot be run."""


class ModuleValidationError(ModuleRunError):
    """Raised when module parameters fail validation."""

    def __init__(self, errors: Sequence[str]):
        self.errors = tuple(str(item) for item in errors if str(item).strip())
        super().__init__("; ".join(self.errors) or "module validation failed")


@dataclass(frozen=True)
class ProcessingModuleEntry:
    """A registered processing module or metadata-only module slot."""

    spec: ProcessingModuleSpec
    module: ProcessingModule | None = None
    origin: str = "extension"
    runner: str = "module"

    @property
    def key(self) -> str:
        return self.spec.key

    @property
    def has_runner(self) -> bool:
        return self.module is not None

    def to_descriptor(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "key": self.spec.key,
            "display_name": self.spec.title,
            "enabled_key": self.spec.enabled_key,
            "summary": self.spec.summary,
            "capabilities": list(self.spec.capabilities),
            "result_kinds": list(self.spec.result_kinds),
            "input_kind": self.spec.input_kind,
            "has_file_match": self.spec.has_file_match,
            "aliases": list(self.spec.aliases),
            "parameter_keys": list(self.spec.parameter_keys),
            "origin": self.origin,
            "runner": {
                "kind": self.runner,
                "available": self.has_runner,
            },
        }
        if self.spec.has_file_match:
            entry["file_match"] = {
                "mode_key": self.spec.match_mode_key,
                "value_key": self.spec.match_value_key,
                "default_mode": self.spec.default_match_mode,
                "default_value": self.spec.default_match_value,
            }
        return entry


class ProcessingModuleRegistry:
    """Runtime registry for built-in and extension processing modules."""

    def __init__(self) -> None:
        self._entries: dict[str, ProcessingModuleEntry] = {}
        self._aliases: dict[str, str] = {}

    @staticmethod
    def _clean_key(value: Any) -> str:
        return str(value or "").strip().upper()

    def _remove_aliases_for(self, key: str) -> None:
        for alias, target in list(self._aliases.items()):
            if target == key:
                self._aliases.pop(alias, None)

    def _validate_spec(self, spec: ProcessingModuleSpec) -> str:
        key = self._clean_key(spec.key)
        if not key:
            raise ModuleRegistrationError("processing module key cannot be empty")
        if key != spec.key:
            raise ModuleRegistrationError(f"processing module key must be uppercase: {spec.key}")
        if not str(spec.enabled_key or "").strip():
            raise ModuleRegistrationError(f"{key} enabled_key cannot be empty")
        if any(not isinstance(item, str) for item in spec.parameter_keys):
            raise ModuleRegistrationError(f"{key} parameter_keys must contain strings")
        parameter_keys = list(spec.parameter_keys)
        if any(not item.strip() or item != item.strip() or item.startswith("_") for item in parameter_keys):
            raise ModuleRegistrationError(f"{key} parameter_keys must contain non-empty public names")
        if len(parameter_keys) != len(set(parameter_keys)):
            raise ModuleRegistrationError(f"{key} parameter_keys cannot contain duplicates")
        return key

    def _register_aliases(self, spec: ProcessingModuleSpec) -> None:
        key = self._clean_key(spec.key)
        for raw_alias in spec.aliases:
            alias = self._clean_key(raw_alias)
            if not alias or alias == key:
                continue
            existing = self._entries.get(alias)
            if existing and existing.key != key:
                raise ModuleRegistrationError(f"alias {alias} conflicts with module key {existing.key}")
            existing_target = self._aliases.get(alias)
            if existing_target and existing_target != key:
                raise ModuleRegistrationError(f"alias {alias} already maps to {existing_target}")
            self._aliases[alias] = key

    def register_spec(
        self,
        spec: ProcessingModuleSpec,
        *,
        origin: str = "extension",
        runner: str = "metadata",
        replace: bool = False,
    ) -> ProcessingModuleEntry:
        key = self._validate_spec(spec)
        if key in self._entries and not replace:
            raise ModuleRegistrationError(f"processing module already registered: {key}")
        if replace:
            self._remove_aliases_for(key)
        entry = ProcessingModuleEntry(spec=spec, module=None, origin=str(origin or "extension"), runner=str(runner or "metadata"))
        self._entries[key] = entry
        self._register_aliases(spec)
        return entry

    def register_module(
        self,
        module: ProcessingModule,
        *,
        origin: str = "extension",
        replace: bool = False,
    ) -> ProcessingModuleEntry:
        if not isinstance(module, ProcessingModule):
            raise ModuleRegistrationError("module must implement the ProcessingModule protocol")
        spec = module.spec
        key = self._validate_spec(spec)
        if key in self._entries and not replace:
            raise ModuleRegistrationError(f"processing module already registered: {key}")
        if replace:
            self._remove_aliases_for(key)
        entry = ProcessingModuleEntry(spec=spec, module=module, origin=str(origin or "extension"), runner="module")
        self._entries[key] = entry
        self._register_aliases(spec)
        return entry

    def unregister(self, data_type: str) -> None:
        key = self.normalize_type(data_type)
        self._entries.pop(key, None)
        self._remove_aliases_for(key)

    def normalize_type(self, value: Any) -> str:
        key = self._clean_key(value)
        return self._aliases.get(key, key)

    def validate_data_types(
        self,
        data_types: Sequence[str] | None,
        *,
        default_all: bool = True,
    ) -> list[str]:
        if not data_types:
            return self.supported_data_types() if default_all else []
        selected: list[str] = []
        invalid: list[str] = []
        for raw in data_types:
            key = self.normalize_type(raw)
            if key not in self._entries:
                invalid.append(str(raw))
                continue
            if key not in selected:
                selected.append(key)
        if invalid:
            raise KeyError(f"Unsupported processing module: {', '.join(invalid)}")
        return selected

    def get_entry(self, data_type: str) -> ProcessingModuleEntry:
        key = self.normalize_type(data_type)
        try:
            return self._entries[key]
        except KeyError as exc:
            raise KeyError(f"Unsupported processing module: {data_type}") from exc

    def get_spec(self, data_type: str) -> ProcessingModuleSpec:
        return self.get_entry(data_type).spec

    def get_module(self, data_type: str) -> ProcessingModule:
        entry = self.get_entry(data_type)
        if entry.module is None:
            raise ModuleRunError(f"{entry.key} is registered without a direct module runner")
        return entry.module

    def list_entries(self, data_types: Sequence[str] | None = None) -> tuple[ProcessingModuleEntry, ...]:
        selected = set(self.validate_data_types(data_types, default_all=True)) if data_types else None
        entries = tuple(self._entries.values())
        if selected is None:
            return entries
        return tuple(entry for entry in entries if entry.key in selected)

    def supported_data_types(self) -> list[str]:
        return list(self._entries.keys())

    def aliases(self) -> dict[str, str]:
        return dict(self._aliases)

    def descriptors(self, data_types: Sequence[str] | None = None) -> list[dict[str, Any]]:
        return [entry.to_descriptor() for entry in self.list_entries(data_types)]

    def catalog(self, data_types: Sequence[str] | None = None) -> dict[str, Any]:
        return {
            "schema_version": MODULE_RUNTIME_SCHEMA_VERSION,
            "execution": "registry_orchestrated",
            "supported_data_types": self.supported_data_types(),
            "aliases": self.aliases(),
            "modules": self.descriptors(data_types),
        }

    def validate_module_params(self, data_type: str, context: ModuleRunContext) -> list[str]:
        module = self.get_module(data_type)
        return [str(item) for item in module.validate_params(context) if str(item).strip()]

    def detect_module_files(self, data_type: str, context: ModuleRunContext) -> tuple[str, ...]:
        module = self.get_module(data_type)
        return tuple(str(item) for item in module.detect_files(context) if str(item).strip())

    def preflight_module(self, data_type: str, context: ModuleRunContext) -> dict[str, Any]:
        entry = self.get_entry(data_type)
        if entry.module is None:
            return {
                "data_type": entry.key,
                "runner": entry.runner,
                "runnable": False,
                "status": "metadata_only",
                "matched": 0,
                "files": [],
                "param_errors": [],
            }
        errors = self.validate_module_params(entry.key, context)
        files = self.detect_module_files(entry.key, context)
        return {
            "data_type": entry.key,
            "runner": entry.runner,
            "runnable": bool(files) and not errors,
            "status": "pass" if files and not errors else "check",
            "matched": len(files),
            "files": list(files),
            "param_errors": errors,
        }

    def run_module(
        self,
        data_type: str,
        context: ModuleRunContext,
        files: Sequence[str] | None = None,
    ) -> ModuleRunResult:
        module = self.get_module(data_type)
        errors = [str(item) for item in module.validate_params(context) if str(item).strip()]
        if errors:
            raise ModuleValidationError(errors)
        resolved_files = tuple(files) if files is not None else tuple(module.detect_files(context))
        return module.run(context, resolved_files)


def build_default_module_registry() -> ProcessingModuleRegistry:
    registry = ProcessingModuleRegistry()
    from electrochem_v6.core.processing_coupled_module import CoupledFEModule
    from electrochem_v6.core.processing_cv_module import CvDirectModule
    from electrochem_v6.core.processing_ecsa_module import EcsaDirectModule
    from electrochem_v6.core.processing_eis_module import EisDirectModule
    from electrochem_v6.core.processing_lsv_module import LsvDirectModule

    modules = {
        module.spec.key: module
        for module in (
            LsvDirectModule(),
            CvDirectModule(),
            EisDirectModule(),
            EcsaDirectModule(),
            CoupledFEModule(),
        )
    }
    for spec in PROCESSING_MODULES:
        registry.register_module(modules[spec.key], origin="builtin")
    return registry


DEFAULT_MODULE_REGISTRY = build_default_module_registry()


def get_processing_module_registry() -> ProcessingModuleRegistry:
    return DEFAULT_MODULE_REGISTRY


def register_processing_module(module: ProcessingModule, *, replace: bool = False) -> ProcessingModuleEntry:
    return DEFAULT_MODULE_REGISTRY.register_module(module, replace=replace)


def register_processing_module_spec(
    spec: ProcessingModuleSpec,
    *,
    origin: str = "extension",
    runner: str = "metadata",
    replace: bool = False,
) -> ProcessingModuleEntry:
    return DEFAULT_MODULE_REGISTRY.register_spec(spec, origin=origin, runner=runner, replace=replace)


def processing_module_catalog(data_types: Sequence[str] | None = None) -> dict[str, Any]:
    return {"status": "success", "catalog": DEFAULT_MODULE_REGISTRY.catalog(data_types)}


__all__ = [
    "DEFAULT_MODULE_REGISTRY",
    "MODULE_RUNTIME_SCHEMA_VERSION",
    "ModuleRegistrationError",
    "ModuleRunError",
    "ModuleValidationError",
    "ProcessingModuleEntry",
    "ProcessingModuleRegistry",
    "build_default_module_registry",
    "get_processing_module_registry",
    "processing_module_catalog",
    "register_processing_module",
    "register_processing_module_spec",
]
