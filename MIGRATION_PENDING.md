# Pure v6 Migration Pending

This folder is the `v6`-only publish skeleton.

It is now self-contained for the migrated `store`, `agent`, `llm`, and processing compatibility layer.
What remains is deeper cleanup and module splitting, not parent-repository import dependency.

## Current blockers

1. `src/electrochem_v6/core/processing_core_v6.py`
   - large migrated compatibility module
   - should be split into smaller v6-native modules over time

2. `src/electrochem_v6/core/pipeline_adapter.py`
   - still framed as a compatibility bridge check

3. `packaging/electrochem_v6.spec`
   - packaging still needs end-to-end validation in this standalone layout

## Minimum migration tasks

1. Split `processing_core_v6.py` into smaller v6-native modules
2. Validate packaging and smoke scripts in the standalone layout

## Completed in this branch

1. Replaced `legacy_runtime.py` legacy imports with native v6 JSON-backed runtime managers
2. `projects.py`, `history.py`, and `conversations.py` now use v6-native runtime singletons
3. Moved v5 `app/llm/*` runtime dependencies into `src/electrochem_v6/llm/`
4. Moved v5 `app/agent/*` runtime dependencies into `src/electrochem_v6/agent/`
5. Internalized processing-core runtime APIs via `processing_core_v6.py`, `processing_compat.py`, and root shim `processing_core.py`
6. Removed parent-directory `sys.path` assumptions from `run_v6.py`, `stress_smoke.py`, and launcher/bootstrap paths

## Publish guidance

- Use `github_publish_bridge/` if you need a publishable self-contained repository right now.
- Use `github_publish_pure_v6/` as the base for finishing the full v6 migration.
