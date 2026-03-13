"""Process template store for v6."""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List

from electrochem_v6.config import ensure_parent_dir, get_templates_file


def _template_file() -> str:
    return str(ensure_parent_dir(get_templates_file()))


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
                "pro-auto-detect": True,
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
                "pro-auto-detect": True,
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
                "pro-auto-detect": True,
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
                "pro-auto-detect": True,
                "pro-plot-grid": True,
                "pro-ecsa-avg-last-n": False,
                "pro-ecsa-use-abs": True,
            },
        },
    },
]


def _builtin_names() -> set[str]:
    return {item["name"] for item in BUILTIN_TEMPLATES}


def _load_user_templates() -> List[Dict[str, Any]]:
    file_path = _template_file()
    if not os.path.exists(file_path):
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return []
    items = payload.get("templates")
    if not isinstance(items, list):
        return []
    clean_items: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        state = item.get("state")
        if not name or not isinstance(state, dict):
            continue
        clean_items.append(
            {
                "name": name,
                "builtin": False,
                "updated_at": str(item.get("updated_at") or ""),
                "state": state,
            }
        )
    return clean_items


def _save_user_templates(items: List[Dict[str, Any]]) -> bool:
    file_path = _template_file()
    try:
        from electrochem_v6.store._json_utils import atomic_write_json
        atomic_write_json(file_path, {"version": "1.0", "templates": items})
        return True
    except Exception:
        return False


def list_process_templates() -> Dict[str, Any]:
    user_items = _load_user_templates()
    items = BUILTIN_TEMPLATES + sorted(user_items, key=lambda x: x.get("name", "").lower())
    return {"status": "success", "templates": items}


def save_process_template(name: str, state: Dict[str, Any], overwrite: bool = False) -> Dict[str, Any]:
    clean_name = str(name or "").strip()
    if not clean_name:
        return {"status": "error", "message": "模板名称不能为空"}
    if len(clean_name) > 80:
        return {"status": "error", "message": "模板名称过长（最多80字符）"}
    if clean_name in _builtin_names():
        return {"status": "error", "message": "内置模板不可覆盖"}
    if not isinstance(state, dict):
        return {"status": "error", "message": "模板状态必须是对象"}

    user_items = _load_user_templates()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    exists_idx = next((i for i, item in enumerate(user_items) if item.get("name") == clean_name), None)
    if exists_idx is not None and not overwrite:
        return {"status": "error", "message": "模板已存在，请确认是否覆盖", "code": "already_exists"}

    payload_item = {
        "name": clean_name,
        "state": state,
        "updated_at": now,
    }
    if exists_idx is None:
        user_items.append(payload_item)
    else:
        user_items[exists_idx] = payload_item

    if not _save_user_templates(user_items):
        return {"status": "error", "message": "模板保存失败"}
    return {"status": "success", "message": "模板已保存", "template": payload_item}


def delete_process_template(name: str) -> Dict[str, Any]:
    clean_name = str(name or "").strip()
    if not clean_name:
        return {"status": "error", "message": "模板名称不能为空"}
    if clean_name in _builtin_names():
        return {"status": "error", "message": "内置模板不可删除"}

    user_items = _load_user_templates()
    new_items = [item for item in user_items if item.get("name") != clean_name]
    if len(new_items) == len(user_items):
        return {"status": "error", "message": "模板不存在"}
    if not _save_user_templates(new_items):
        return {"status": "error", "message": "模板删除失败"}
    return {"status": "success", "message": "模板已删除", "name": clean_name}
