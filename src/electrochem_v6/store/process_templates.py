"""SQLite-backed process template service."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List

from .runtime import get_database

BUILTIN_TEMPLATES: List[Dict[str, Any]] = [
    {
        "name": "LSV_常用模板",
        "builtin": True,
        "updated_at": "builtin",
        "state": {
            "selected_types": ["LSV"],
            "values": {
                "pro-lsv-target": "10,100",
                "pro-lsv-tafel": "1-10",
                "pro-lsv-match": "prefix",
                "pro-lsv-prefix": "LSV",
                "pro-lsv-ir-method": "auto",
                "pro-lsv-ir-points": "10",
            },
            "checks": {
                "pro-plot-grid": True,
                "pro-use-abs-current": True,
                "pro-lsv-mark-targets": True,
                "pro-lsv-tafel-enabled": False,
                "pro-lsv-ir-enabled": False,
                "pro-lsv-onset-enabled": False,
                "pro-lsv-halfwave-enabled": False,
            },
        },
    },
    {
        "name": "CV_常用模板",
        "builtin": True,
        "updated_at": "builtin",
        "state": {
            "selected_types": ["CV"],
            "values": {
                "pro-cv-match": "prefix",
                "pro-cv-prefix": "CV",
                "pro-cv-peaks-smooth": "5",
                "pro-cv-peaks-height": "1.0",
                "pro-cv-peaks-dist": "5",
                "pro-cv-peaks-max": "2",
            },
            "checks": {
                "pro-plot-grid": True,
                "pro-use-abs-current": True,
                "pro-cv-peaks-enabled": True,
            },
        },
    },
    {
        "name": "EIS_常用模板",
        "builtin": True,
        "updated_at": "builtin",
        "state": {
            "selected_types": ["EIS"],
            "values": {
                "pro-eis-match": "prefix",
                "pro-eis-prefix": "EIS",
            },
            "checks": {
                "pro-plot-grid": True,
                "pro-eis-plot-nyquist": True,
                "pro-eis-plot-bode": False,
            },
        },
    },
    {
        "name": "ECSA_常用模板",
        "builtin": True,
        "updated_at": "builtin",
        "state": {
            "selected_types": ["ECSA"],
            "values": {
                "pro-ecsa-match": "prefix",
                "pro-ecsa-prefix": "ECSA",
                "pro-ecsa-ev": "0.10",
                "pro-ecsa-last-n": "1",
                "pro-ecsa-cs-value": "40",
                "pro-ecsa-cs-unit": "uF/cm2",
            },
            "checks": {
                "pro-plot-grid": True,
                "pro-ecsa-avg-last-n": False,
                "pro-ecsa-use-abs": True,
            },
        },
    },
]


def _current_schema_version() -> str:
    # Local import avoids loading the processing service while the store
    # package itself is still being initialized.
    from electrochem_v6.core.processing_registry import PARAM_SCHEMA_VERSION

    return PARAM_SCHEMA_VERSION


def _builtin_names() -> set[str]:
    return {str(item["name"]) for item in BUILTIN_TEMPLATES}


def _builtin_templates() -> list[Dict[str, Any]]:
    items = deepcopy(BUILTIN_TEMPLATES)
    schema_version = _current_schema_version()
    for item in items:
        item["state"]["schema_version"] = schema_version
    return items


def _prepare_state(state: Dict[str, Any]) -> tuple[Dict[str, Any] | None, str | None]:
    if not isinstance(state, dict):
        return None, "模板状态必须是对象"
    selected_types = state.get("selected_types", [])
    values = state.get("values", {})
    checks = state.get("checks", {})
    if not isinstance(selected_types, list) or any(not isinstance(item, str) for item in selected_types):
        return None, "模板处理方式必须是字符串列表"
    if not isinstance(values, dict) or not isinstance(checks, dict):
        return None, "模板参数必须是对象"
    prepared = deepcopy(state)
    prepared["schema_version"] = _current_schema_version()
    prepared["selected_types"] = [str(item).strip().upper() for item in selected_types if str(item).strip()]
    prepared["values"] = {str(key): value for key, value in values.items() if str(key).strip()}
    prepared["checks"] = {str(key): bool(value) for key, value in checks.items() if str(key).strip()}
    return prepared, None


def list_process_templates() -> Dict[str, Any]:
    user_items = get_database().list_process_templates()
    items = _builtin_templates() + sorted(user_items, key=lambda item: str(item.get("name") or "").lower())
    return {
        "status": "success",
        "schema_version": _current_schema_version(),
        "templates": items,
    }


def save_process_template(name: str, state: Dict[str, Any], overwrite: bool = False) -> Dict[str, Any]:
    clean_name = str(name or "").strip()
    if not clean_name:
        return {"status": "error", "message": "模板名称不能为空"}
    if len(clean_name) > 80:
        return {"status": "error", "message": "模板名称过长（最多80字符）"}
    if clean_name in _builtin_names():
        return {"status": "error", "message": "内置模板不可覆盖"}
    prepared, error = _prepare_state(state)
    if error or prepared is None:
        return {"status": "error", "message": error or "模板状态无效"}

    database = get_database()
    existing = next(
        (item for item in database.list_process_templates() if item.get("name") == clean_name),
        None,
    )
    if existing is not None and not overwrite:
        return {
            "status": "error",
            "message": "模板已存在，请确认是否覆盖",
            "code": "already_exists",
        }
    if not database.save_process_template(clean_name, prepared, overwrite=overwrite):
        if not overwrite:
            return {
                "status": "error",
                "message": "模板已存在，请确认是否覆盖",
                "code": "already_exists",
            }
        return {"status": "error", "message": "模板保存失败"}

    payload_item = {
        "name": clean_name,
        "builtin": False,
        "state": prepared,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    return {"status": "success", "message": "模板已保存", "template": payload_item}


def delete_process_template(name: str) -> Dict[str, Any]:
    clean_name = str(name or "").strip()
    if not clean_name:
        return {"status": "error", "message": "模板名称不能为空"}
    if clean_name in _builtin_names():
        return {"status": "error", "message": "内置模板不可删除"}
    if not get_database().delete_process_template(clean_name):
        return {"status": "error", "message": "模板不存在"}
    return {"status": "success", "message": "模板已删除", "name": clean_name}
