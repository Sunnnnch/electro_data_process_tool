# Processing Module Extension Guide

This guide describes the v6 extension path for new electrochemical processing modules.

## Goal

New modules should be added through a small contract instead of editing every service layer directly.

The intended module shape is:

1. Define a `ProcessingModuleSpec`.
2. Implement the `ProcessingModule` protocol.
3. Register the module with the runtime registry.
4. Add UI fields only after the backend contract is stable.

## Minimal Module

```python
from electrochem_v6.core.processing_module_contract import ModuleRunContext, ModuleRunResult
from electrochem_v6.core.processing_module_runtime import register_processing_module
from electrochem_v6.core.processing_registry import ProcessingModuleSpec


class FaradaicEfficiencyModule:
    spec = ProcessingModuleSpec(
        "FE2",
        "fe2_enabled",
        display_name="FE2",
        summary="Faradaic efficiency and product selectivity extension",
        capabilities=("faradaic_efficiency", "product_selectivity"),
        result_kinds=("summary_table", "history_record"),
        input_kind="product_table",
        aliases=("FE2_SELECTIVITY",),
        parameter_keys=("fe2_products_file", "fe2_charge_c"),
    )

    def detect_files(self, context: ModuleRunContext):
        return []

    def validate_params(self, context: ModuleRunContext):
        if not context.params.get("products_file"):
            return ["products_file is required"]
        return []

    def run(self, context: ModuleRunContext, files):
        return ModuleRunResult(data_type="FE2", messages=("processed",))


register_processing_module(FaradaicEfficiencyModule())
```

## Current Built-In Modules

`LSV`, `CV`, `EIS`, `ECSA`, and `COUPLED/FE` are registered as built-in direct `module` runners. They can be discovered, preflighted, and run through the same runtime module contract.

The historical `processing_pipeline.py` and monolithic executor have been removed. Integrations must call `process_service.process_folder()` or `run_module_pipeline()` so every processing path uses the same registry and result contract.

New extension modules should use direct `module` runners from the beginning. After a module matures, it can be promoted into the main UI and processing parameter schema without changing its execution contract.

Extension-only request parameters must be declared in `ProcessingModuleSpec.parameter_keys`. The service rejects undeclared keys in the request `params` object so spelling mistakes cannot be silently ignored. Built-in modules obtain their allowed keys from the central parameter schema.

## Formula And Provenance Metadata

Modules that calculate derived metrics should attach formula metadata so results can be audited later:

1. Add formulas to `processing_formula.py` with stable keys, variables, assumptions, and units.
2. Attach `formula_key` to each metric when a metric is calculated from a specific equation.
3. Include the relevant `formula_keys` in module or result metadata.
4. Keep formula keys conditional when a value may come from different sources. For example, COUPLED/FE only marks `coupled.charge_from_current_time` when total charge is derived from current and time.

Run manifests include formula metadata and input file identity fields such as size, modified time, and SHA-256 hashes. This makes result review and reruns easier when a user asks why a number was produced.

The user-facing report is written to `run_report.html`; a `run_report.md` companion is retained for text-based integrations. Both are generated from the manifest and should remain readable rather than exhaustive. Keep detailed machine-readable provenance in `run_manifest.json`.

## Discovery API

Clients can query the runtime catalog:

```http
GET /api/v1/process/modules
GET /api/v1/process/modules?data_types=LSV,FE
```

The response includes module keys, aliases, input kind, capabilities, result kinds, origin, and runner availability.

## Parameter Schema API

Clients must obtain processing defaults and validation rules from the backend:

```http
GET /api/v1/process/schema
GET /api/v1/process/schema?data_types=LSV,EIS
```

The schema owns parameter value types, runtime defaults, UI defaults, numeric bounds, allowed options, groups, labels, and presets. The browser client keeps only the mapping from parameter keys to DOM controls; it must not duplicate those rules in JavaScript or HTML attributes.

Use the canonical processing request shape for new integrations:

```json
{
  "folder_path": "D:/data/sample",
  "data_types": ["LSV", "EIS"],
  "params": {
    "area": 1.0,
    "potential_mode": "manual",
    "potential_offset": 0.0
  }
}
```

When adding a parameter:

1. Declare it in `processing_registry.py` with its type, default, bounds, options, group, and module ownership.
2. Add a DOM binding in `process_schema.js` only when the parameter is exposed in the built-in browser UI.
3. Read it through the normal module context; do not add a second default in the service or frontend.
4. Extend the schema/binding contract test and add focused behavior tests.

Increment `PARAM_SCHEMA_VERSION` whenever a schema-visible contract changes. Persisted templates should be validated against the current schema when loaded rather than silently restoring obsolete defaults.

## Recommended Order For New Modules

1. Add calculation and IO helpers under `src/electrochem_v6/core/`.
2. Add focused unit tests for calculation and parsing.
3. Implement `ProcessingModule`.
4. Register it in application startup or module import code.
5. Add a preflight test through `preflight_module`.
6. Add formula/provenance tests for calculated metrics.
7. Add UI fields and parameter schema only after the backend behavior is stable.
