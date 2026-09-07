"""Evidence-based report documents, safe renderers, and local export services.

Report documents contain data, never trusted HTML. Missing historical evidence
stays missing: this module does not merge today's processing defaults into a run.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import os
import re
from copy import deepcopy
from datetime import datetime
from html import escape
from numbers import Real
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import quote, urlsplit

from PIL import Image

from electrochem_v6.core.history_compare import history_metrics_for_display

MISSING = "未记录 / Not recorded"
REPORT_SCHEMA_VERSION = "1.0"
_IMAGE_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif", "WEBP": "image/webp"}
_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_MAX_EMBED_BYTES = 40 * 1024 * 1024
_SECRET_KEYS = ("api_key", "apikey", "password", "secret", "authorization", "access_token", "refresh_token")
_CONDITION_KEYS = (
    "electrolyte", "electrolyte_concentration", "ph", "pH", "temperature", "temperature_c",
    "reference_electrode", "electrode", "area", "area_cm2", "loading_mg_cm2", "gas",
    "potential_mode", "potential_offset", "offset", "eq_potential",
)
_PARAMETER_LABELS = {
    "area": "几何面积 (cm²)", "area_cm2": "几何面积 (cm²)", "potential_offset": "电位偏移 (V)",
    "offset": "电位偏移 (V)", "potential_mode": "电位换算方式", "eq_potential": "平衡电位 (V)",
    "electrolyte": "电解液", "temperature": "温度", "temperature_c": "温度 (°C)", "ph": "pH", "pH": "pH",
    "reference_electrode": "参比电极", "target_current": "目标电流密度 (mA/cm²)", "lsv_target_current": "目标电流密度 (mA/cm²)",
    "tafel_enabled": "Tafel 拟合", "tafel_range": "Tafel 区间 (mA/cm²)", "use_abs_current": "使用电流绝对值",
    "overpotential_enabled": "计算过电位", "ir_compensation_enabled": "iR 补偿", "ir_source": "iR 电阻来源",
    "ir_manual_ohm": "手动电阻 (Ω)", "ir_method": "电阻提取方法", "ir_validation_mode": "iR 验证方式",
    "cv_scan_rate_v_s": "扫速 (V/s)", "scan_rate_v_s": "扫速 (V/s)", "cv_cycle_numbers": "所选圈次",
    "cycle_numbers": "所选圈次", "cv_peaks_enabled": "峰检测", "peaks_enabled": "峰检测",
    "ecsa_ev": "取值电位 (V)", "ev": "取值电位 (V)", "ecsa_last_n": "最后圈数", "last_n": "最后圈数",
    "ecsa_avg_last_n": "多圈平均", "avg_last_n": "多圈平均", "ecsa_cs_value": "比电容 Cs", "cs_value": "比电容 Cs",
    "ecsa_cs_unit": "Cs 单位", "cs_unit": "Cs 单位", "ecsa_use_abs_delta": "电流差取绝对值",
    "eis_circuit_model": "等效电路", "eis_randles_fit": "阻抗拟合", "eis_fit_min_r2": "拟合最低 R²",
    "coupled_input_mode": "定量方式", "coupled_products_sheet": "定量表工作表",
}
_CALCULATION_KEYS = (
    "target_current", "lsv_target_current", "use_abs_current", "tafel_enabled", "tafel_range",
    "overpotential_enabled", "onset_enabled", "onset_current", "halfwave_enabled", "halfwave_current",
    "ir_compensation_enabled", "ir_source", "ir_manual_ohm", "ir_eis_search_scope", "ir_linear_points",
    "ir_validation_mode", "ir_method", "ir_eis_file", "scan_rate_v_s", "cv_scan_rate_v_s",
    "cv_cycle_numbers", "cycle_numbers", "cv_cycle_reversal_tolerance", "cv_cycle_min_segment_points",
    "cv_peaks_enabled", "peaks_enabled", "cv_peaks_smooth", "cv_peaks_min_height", "cv_peaks_min_dist", "cv_peaks_max",
    "ev", "ecsa_ev", "last_n", "ecsa_last_n", "avg_last_n", "ecsa_avg_last_n",
    "cs_value", "ecsa_cs_value", "cs_unit", "ecsa_cs_unit", "ecsa_use_abs_delta",
    "eis_circuit_model", "eis_fit_min_r2", "eis_randles_fit", "eis_fit_min_points", "coupled_input_mode",
    "coupled_products_file", "coupled_products_sheet", "coupled_peak_method_source", "coupled_peak_method_file",
)


def _map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _items(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def redact_report_value(value: Any) -> Any:
    """Redact secrets recursively, including objects nested inside arrays."""
    if isinstance(value, Mapping):
        return {
            str(key): "***REDACTED***" if any(token in str(key).lower() for token in _SECRET_KEYS)
            else redact_report_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_report_value(item) for item in value]
    if hasattr(value, "tolist"):
        return redact_report_value(value.tolist())
    if hasattr(value, "item"):
        return redact_report_value(value.item())
    return value


def _text(value: Any) -> str:
    if value is None or (isinstance(value, str) and value == ""):
        return MISSING
    if isinstance(value, (Mapping, list, tuple)):
        return json.dumps(redact_report_value(value), ensure_ascii=False, default=str)
    return str(value)


def _md(value: Any) -> str:
    return re.sub(r"([\\`\[\]])", r"\\\1", escape(_text(value), quote=False)).replace("|", "\\|").replace("\r", "").replace("\n", "<br>")


def _section(heading: str, *, fields=None, paragraphs=None, columns=None, rows=None, payload=None, level=2) -> dict[str, Any]:
    block: dict[str, Any] = {"heading": heading, "level": level}
    for key, value in (("fields", fields), ("paragraphs", paragraphs), ("columns", columns), ("rows", rows)):
        if value is not None:
            block[key] = value
    if payload is not None:
        block["json"] = redact_report_value(payload)
    return block


def _known_fields(params: Mapping[str, Any], keys: Sequence[str]) -> list[list[Any]]:
    return [[key, params[key]] for key in keys if key in params]


def _display_number(value: Any) -> str:
    if isinstance(value, Real) and not isinstance(value, bool):
        return f"{float(value):.6g}" if math.isfinite(float(value)) else MISSING
    return _text(value)


def _short_id(value: Any) -> str:
    text = str(value or "")
    return (text[:8] if len(text) > 12 else text) or MISSING


def _brief_parameters(params: Mapping[str, Any]) -> list[list[Any]]:
    fields = []
    seen = set()
    aliases = {"offset": "potential_offset", "target_current": "lsv_target_current", "area_cm2": "area",
               "ev": "ecsa_ev", "last_n": "ecsa_last_n", "avg_last_n": "ecsa_avg_last_n",
               "cs_value": "ecsa_cs_value", "cs_unit": "ecsa_cs_unit", "cycle_numbers": "cv_cycle_numbers",
               "peaks_enabled": "cv_peaks_enabled", "scan_rate_v_s": "cv_scan_rate_v_s"}
    for key in (*_CONDITION_KEYS, *_CALCULATION_KEYS):
        if key not in params or (key in aliases and aliases[key] in params) or key.endswith("_file"):
            continue
        if key.startswith("ir_") and key != "ir_compensation_enabled" and params.get("ir_compensation_enabled") is False:
            continue
        if key == "tafel_range" and params.get("tafel_enabled") is False:
            continue
        if key.startswith("cv_peaks_") and key != "cv_peaks_enabled" and params.get("cv_peaks_enabled") is False:
            continue
        if key in {"onset_current", "halfwave_current"} and params.get(key.replace("_current", "_enabled")) is False:
            continue
        value = params[key]
        if value is None or value == "" or isinstance(value, Mapping):
            continue
        label = _PARAMETER_LABELS.get(key, key)
        if label in seen:
            continue
        seen.add(label)
        if isinstance(value, bool):
            display = "启用" if value else "关闭"
        elif isinstance(value, (list, tuple)):
            display = ", ".join(_display_number(item) for item in value)
        else:
            display = _display_number(value)
        fields.append([label, display])
    return fields


def _scope_fields(scope: Mapping[str, Any]) -> list[list[Any]]:
    modes = {"run": "单次完整运行", "project": "项目全部可用记录", "run_ids": "指定运行", "record_keys": "指定历史记录", "supplied_records": "提供的历史记录"}
    fields = [["范围", modes.get(str(scope.get("mode")), MISSING)]]
    fields.extend([[label, scope[key]] for key, label in (("run_count", "运行数"), ("record_count", "历史记录数"),
                                                       ("normalized_result_count", "运行结果数")) if key in scope])
    if "include_archived" in scope:
        fields.append(["包含归档", "是" if scope["include_archived"] else "否"])
    return fields


def _quality_brief(quality: Mapping[str, Any], reports: Sequence[Any] = (), *, heading: str = "Quality Summary") -> dict[str, Any]:
    labels = {"total_files": "检查文件", "passed": "通过", "failed": "失败", "warnings": "有警告", "skipped": "跳过"}
    fields = [[label, quality[key]] for key, label in labels.items() if key in quality and not isinstance(quality[key], (Mapping, list))]
    notes = []
    for raw in [quality, *_items(quality.get("files")), *reports]:
        item = _map(raw)
        for key in ("issues", "warnings", "suggestions"):
            for value in _items(item.get(key)):
                note = str(_map(value).get("message") or _map(value).get("description") or value)
                if "�" in note:
                    note = "原始质量提示含不可识别字符，详见附录原始记录。"
                if note not in notes:
                    notes.append(note)
    paragraphs = [item[:180] + ("…（完整提示见附录）" if len(item) > 180 else "") for item in notes[:3]]
    if len(notes) > 3:
        paragraphs.append(f"另有 {len(notes) - 3} 条提示，见附录。")
    if not fields and not paragraphs:
        paragraphs = ["质量检查结果未记录。" if not quality and not reports else "未记录质量告警；详细检查数据见附录。"]
    return _section(heading, fields=fields, paragraphs=paragraphs)


def _source_status(item: Mapping[str, Any]) -> str:
    path = str(item.get("path") or "")
    if not path:
        return "仅有历史标识；当前来源位置未记录"
    if path.startswith(("\\\\", "//")):
        return "网络位置未检查；指纹为运行时记录"
    try:
        present = Path(path).is_file()
    except OSError:
        return "当前来源不可访问"
    if not present:
        return "当前源文件缺失；如有源归档请单独恢复"
    return "当前文件存在；未重新核验历史 SHA-256" if item.get("sha256") else "当前文件存在；历史 SHA-256 未记录"


def _validated_image(path: Any, roots: Sequence[str]) -> dict[str, Any]:
    """Only embed verified raster files contained in a recorded output root."""
    raw = str(path or "")
    figure: dict[str, Any] = {"path": raw, "caption": Path(raw).name or "图表", "status": "图表位置未验证"}
    try:
        scheme = urlsplit(raw).scheme.lower()
    except ValueError:
        return figure
    if not raw or raw.startswith(("\\\\", "//")) or scheme in {"http", "https", "javascript", "data"}:
        return figure
    local_roots = [root for root in roots if not str(root).startswith(("\\\\", "//"))]
    candidates = [Path(raw)] if Path(raw).is_absolute() else [Path(root) / raw for root in local_roots]
    resolved_roots = []
    for root in local_roots:
        try:
            resolved_roots.append(Path(root).resolve())
        except OSError:
            continue
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            if not any(resolved.is_relative_to(root) for root in resolved_roots):
                continue
            if not resolved.is_file():
                figure["status"] = "图表文件缺失"
                continue
            if resolved.stat().st_size > _MAX_IMAGE_BYTES:
                with Image.open(resolved) as image:
                    if str(image.format) not in _IMAGE_TYPES or image.width * image.height > 40_000_000:
                        figure["status"] = "图表格式或尺寸不支持安全嵌入"
                        return figure
                    image.verify()
                figure.update(href=resolved.as_uri(), status="图表超过嵌入大小限制；可打开原文件")
                return figure
            content = resolved.read_bytes()
            with Image.open(io.BytesIO(content)) as image:
                mime = _IMAGE_TYPES.get(str(image.format))
                if not mime or image.width * image.height > 40_000_000:
                    figure["status"] = "图表格式或尺寸不支持安全嵌入"
                    return figure
                image.verify()
            figure.update(
                data_uri=f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}",
                href=resolved.as_uri(), status="已验证并嵌入", byte_count=len(content),
            )
            return figure
        except (OSError, ValueError, Image.DecompressionBombError):
            figure["status"] = "图表不可读取或不是有效栅格图像"
    return figure


def _figures(paths: Sequence[Any], roots: Sequence[str]) -> list[dict[str, Any]]:
    result = []
    used = set()
    total = 0
    for path in paths:
        raw = str(path or "")
        if Path(raw).suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"} or raw in used:
            continue
        used.add(raw)
        figure = _validated_image(raw, roots)
        total += int(figure.get("byte_count", 0))
        if total > _MAX_EMBED_BYTES:
            figure.pop("data_uri", None)
            figure["status"] = "报告图表总量超过嵌入限制；可打开原文件"
        result.append(figure)
    return result


def _safe_href(value: Any) -> str | None:
    text = str(value or "")
    if any(ord(char) < 32 or char in '<>"`\\' for char in text):
        return None
    try:
        parsed = urlsplit(text)
    except ValueError:
        return None
    if parsed.scheme == "file" and not parsed.netloc:
        return text
    # Relative paths are generated by export_report_document, never raw input.
    if not parsed.scheme and re.fullmatch(r"[A-Za-z0-9_.-]+_assets/[a-f0-9]{64}\.(?:png|jpg|gif|webp)", text):
        return text
    return None


def _safe_image_uri(value: Any) -> str | None:
    text = str(value or "")
    return text if re.fullmatch(r"data:image/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+", text) else None


def _sample_label(item: Mapping[str, Any]) -> str:
    sample = str(item.get("sample_name") or item.get("file_name") or "未命名样品")
    source = _map(item.get("source"))
    path = source.get("path") or item.get("file_path") or source.get("file_name") or item.get("file_name")
    filename = str(path or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return f"{sample} · {filename}" if filename and filename != sample else sample


def _metric_rows(results: Sequence[Any]) -> list[list[Any]]:
    rows = []
    for result in results:
        item = _map(result)
        seen = set()
        for raw in _items(item.get("metrics")):
            metric = _map(raw)
            if isinstance(metric.get("value"), (Mapping, list, tuple)):
                continue
            identity = (metric.get("key"), metric.get("unit"), metric.get("method"))
            if identity in seen:
                continue
            seen.add(identity)
            label = str(metric.get("label") or metric.get("key") or MISSING)
            metadata = _map(metric.get("metadata"))
            if metadata.get("definition_key") == "lsv.tafel_slope":
                label = "Tafel 斜率"
            elif metadata.get("definition_key") in {"lsv.potential_at_current", "lsv.overpotential_at_current"}:
                kind = "E" if metadata.get("definition_key") == "lsv.potential_at_current" else "η"
                label = f"{kind} @ {_display_number(metadata.get('target_current_mA_cm2'))} mA/cm²"
            rows.append([
                _sample_label(item), item.get("data_type"), label,
                _display_number(metric.get("value")), metric.get("unit") or "—", metric.get("method") or "—",
            ])
    return rows


def _formula_blocks(calculation: Mapping[str, Any], *, prefix: str = "") -> list[dict[str, Any]]:
    formulas = _items(calculation.get("formulas"))
    version = calculation.get("formula_schema_version") or calculation.get("schema_version")
    blocks = [_section(prefix + "Calculation Formulas", fields=[["Formula schema", version]])]
    if not formulas:
        blocks[0]["paragraphs"] = [
            f"已记录公式版本 {version}；本次清单未保存公式条目，未据当前版本补齐。" if version
            else "公式版本和公式内容未记录；未使用当前版本自动补齐。"
        ]
    for item in formulas:
        formula = _map(item)
        blocks.append(_section(str(formula.get("name") or "Formula"), fields=[
            ["Key", formula.get("key")], ["Expression", formula.get("expression")], ["Result unit", formula.get("result_unit")],
        ], payload=formula, level=3))
    return blocks


def build_run_report_document(manifest: Mapping[str, Any], *, generated_at: str | None = None) -> dict[str, Any]:
    """Build a report using recorded manifest fields, without new defaults."""
    manifest = _map(redact_report_value(manifest))
    run, app, outputs = _map(manifest.get("run")), _map(manifest.get("app")), _map(manifest.get("outputs"))
    params, calculation = _map(manifest.get("parameters")), _map(manifest.get("calculation"))
    normalized = _items(manifest.get("processing_results"))
    files = _items(_map(manifest.get("inputs")).get("files"))
    quality = _map(manifest.get("quality"))
    scope = dict(_map(manifest.get("report_scope"))) or {
        "mode": "run", "run_ids": [run["run_id"]] if run.get("run_id") else [],
        "run_count": 1 if run.get("run_id") else 0, "record_count": len(normalized),
        "record_count_basis": "normalized_processing_results", "normalized_result_count": len(normalized), "truncated": False,
    }
    summary = [
        _section("Run Summary", fields=[
            ["运行编号", _short_id(run.get("run_id"))], ["处理时间", run.get("generated_at")],
            ["数据类型", ", ".join(str(item) for item in _items(run.get("data_types")))],
            ["运行状态", _map(manifest.get("processing")).get("result_state")],
            *_scope_fields(scope),
        ]),
        _section("实验条件与关键参数", fields=_brief_parameters(params), paragraphs=[
            "仅展示保存的条件和计算参数；未保存的实验条件不能确认。" if params else "历史运行参数未记录，无法确认使用的计算设置。"
        ]),
        _section("主要结果 / Key Results", columns=["样品 / 来源文件", "类型", "指标", "数值", "单位", "方法"], rows=_metric_rows(normalized),
                 paragraphs=[] if normalized else ["该历史清单未保存逐样品指标；不能仅凭结果计数还原实验结果。"]),
        _quality_brief(quality, _items(manifest.get("quality_reports"))),
    ]
    paths = _items(outputs.get("output_files"))
    for item in normalized:
        paths.extend(_items(_map(item).get("artifacts")))
    roots = [str(outputs["output_dir"])] if outputs.get("output_dir") else []
    appendix = [
        _section("运行身份与完整范围", payload={"run": run, "scope": scope, "app": app}),
        _section("完整运行参数 / Complete Parameters", payload=params, paragraphs=[] if params else ["参数缺失，未补入当前默认值。"]),
        _section("完整逐样品结果（保留原始精度）", payload=normalized),
        _section("完整质量与处理记录", payload={"quality": quality, "quality_reports": manifest.get("quality_reports", []),
                 "processing": manifest.get("processing"), "skipped_errors": manifest.get("skipped_errors", [])}),
        _section("逐文件实际处理信息", payload=[
            {"sample_name": _map(item).get("sample_name"), "source": _map(item).get("source"), "metadata": _map(item).get("metadata")}
            for item in normalized
        ]),
        *_formula_blocks(calculation),
        _section("iR Compensation Provenance", payload=calculation.get("ir_compensation") or {},
                 paragraphs=[] if calculation.get("ir_compensation") else ["未记录逐文件 iR 来源；不能从缺失字段断言已启用或未启用。"]),
        _section("Input File Fingerprints", columns=["类型", "源文件", "路径", "大小", "SHA-256", "当前来源状态"], rows=[
            [_map(item).get("data_type"), _map(item).get("file_name"), _map(item).get("path"), _map(item).get("size_bytes"), _map(item).get("sha256"), _source_status(_map(item))]
            for item in files
        ], paragraphs=[] if files else ["输入文件及历史指纹未记录。"]),
        _section("完整输入来源记录（含辅助输入和归档位置）", payload=files),
        _section("软件与来源版本", fields=[
            ["Processing app version", app.get("version") or manifest.get("app_version")],
            ["Manifest schema", manifest.get("manifest_schema_version")], ["Formula schema", calculation.get("formula_schema_version")],
            ["Report schema", REPORT_SCHEMA_VERSION], ["Source archive", manifest.get("source_archive_path")],
            ["Source archive SHA-256", manifest.get("source_archive_sha256")],
            ["Parent run", run.get("parent_run_id") or _map(manifest.get("replay")).get("parent_run_id")],
            ["Parent record", run.get("parent_record_key") or _map(manifest.get("replay")).get("parent_record_key")],
            ["Engine", manifest.get("engine")], ["Source integrity", _map(manifest.get("inputs")).get("integrity")],
            ["Results provenance", manifest.get("results_provenance") or ("保存的运行清单" if normalized else None)],
        ]),
        _section("Output Files", paragraphs=[str(item) for item in paths]),
    ]
    return {
        "title": "ElectroChem Run Report", "subtitle": "可复现运行报告",
        "generated_at": generated_at or datetime.now().isoformat(timespec="seconds"),
        "scope": scope, "summary": summary, "figures": _figures(paths, roots), "appendix": appendix,
    }


def _load_recipe(run_id: str) -> Mapping[str, Any]:
    try:
        from electrochem_v6.store.run_recipes import get_run_recipe
    except ImportError:
        return {}
    return _map(get_run_recipe(run_id))


def _manifest_from_recipe(recipe: Mapping[str, Any]) -> dict[str, Any]:
    """Use only saved evidence, including history fallback for older recipes."""
    manifest = deepcopy(dict(_map(recipe.get("manifest"))))
    manifest.setdefault("parameters", deepcopy(recipe.get("params", {})))
    manifest.setdefault("inputs", {"files": deepcopy(recipe.get("inputs", []))})
    manifest.setdefault("app", {"name": "ElectroChem", "version": recipe.get("app_version")})
    manifest.setdefault("run", {"run_id": recipe.get("run_id"), "project_id": recipe.get("project_id"), "data_types": recipe.get("data_types"), "generated_at": recipe.get("created_at")})
    manifest["run"].update(parent_run_id=recipe.get("parent_run_id"), parent_record_key=recipe.get("parent_record_key"))
    manifest.setdefault("outputs", {"output_dir": recipe.get("output_dir"), "output_files": []})
    manifest.setdefault("processing", {"result_state": recipe.get("status")})
    manifest.setdefault("calculation", {"formula_schema_version": recipe.get("formula_schema_version")})
    manifest.setdefault("engine", recipe.get("engine"))
    manifest["source_archive_path"] = recipe.get("source_archive_path")
    manifest["source_archive_sha256"] = recipe.get("source_archive_sha256")
    if recipe.get("source_integrity") is not None:
        manifest["inputs"].setdefault("integrity", recipe.get("source_integrity"))
    if not manifest.get("processing_results") and recipe.get("record_keys"):
        from electrochem_v6.store.history import get_history_detail

        restored = []
        for key in _items(recipe.get("record_keys")):
            record = _map(get_history_detail(str(key)).get("record"))
            if not record or str(record.get("run_id") or "") != str(recipe.get("run_id") or ""):
                continue
            restored.append({
                "sample_name": record.get("sample_name") or record.get("file_name"), "data_type": record.get("type"),
                "metrics": [{"key": key, "value": value} for key, value in _map(record.get("results")).items()],
                "source": {"path": record.get("file_path"), "file_name": record.get("file_name")},
                "artifacts": record.get("output_files") or [], "metadata": {"history_record_key": record.get("record_key")},
            })
        if restored:
            manifest["processing_results"] = restored
            manifest["results_provenance"] = "运行清单未保存逐项结果；由关联历史记录恢复，未推断缺失单位或方法。"
    manifest["report_scope"] = {
        "mode": "run", "run_ids": [str(recipe.get("run_id"))], "run_count": 1,
        "record_keys": _items(recipe.get("record_keys")), "record_count": len(_items(recipe.get("record_keys"))),
        "normalized_result_count": len(_items(manifest.get("processing_results"))),
        "project_id": recipe.get("project_id"), "truncated": False,
    }
    return manifest


def _record_params(record: Mapping[str, Any], recipe: Mapping[str, Any]) -> Mapping[str, Any]:
    for value in (record.get("parameters"), record.get("params"), recipe.get("params"), _map(recipe.get("manifest")).get("parameters")):
        if isinstance(value, Mapping) and value:
            return _map(redact_report_value(value))
    return {}


def _record_inputs(record: Mapping[str, Any], recipe: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Keep record reports from accidentally acquiring other samples' inputs."""
    manifest = _map(recipe.get("manifest"))
    references = _items(recipe.get("inputs")) or _items(_map(manifest.get("inputs")).get("files"))
    source_path = str(record.get("file_path") or "")
    def normalize(path):
        return os.path.normcase(os.path.abspath(str(path)))

    record_ref = next((_map(item) for item in _items(recipe.get("records"))
                       if _map(item).get("record_key") == record.get("record_key")), {})
    selected_paths = {normalize(path) for path in _items(record_ref.get("input_paths"))}
    if not selected_paths and source_path:
        selected_paths = {normalize(source_path)}
    matched = []
    for item in references:
        ref = _map(item)
        candidate = str(ref.get("path") or "")
        if candidate and selected_paths:
            base, path = normalize(source_path), normalize(candidate)
            dependent = bool(selected_paths & {normalize(item) for item in _items(ref.get("for_paths"))})
            if path in selected_paths or (source_path and not record_ref and path.startswith(base.rstrip(os.sep) + os.sep)) or dependent:
                matched.append(ref)
    return matched or ([{"path": source_path, "file_name": record.get("file_name"), "data_type": record.get("type")}] if source_path else [])


def _record_results(record: Mapping[str, Any], recipe: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Associate charts by saved source identity, never by a shared folder label."""
    candidates = [_map(item) for item in _items(_map(recipe.get("manifest")).get("processing_results"))
                  if _map(item).get("data_type") == record.get("type")]
    source_path = str(record.get("file_path") or "")
    if not source_path:
        matches = [item for item in candidates if item.get("sample_name") == record.get("sample_name")]
        return matches if len(matches) == 1 else []

    def identity(path):
        return os.path.normcase(os.path.abspath(str(path)))

    source_key = identity(source_path)
    primary_paths = {identity(item["path"]) for item in _record_inputs(record, recipe)
                     if item.get("path") and item.get("role") in {None, "primary"}}
    matches = []
    for item in candidates:
        source = str(_map(item.get("source")).get("path") or "")
        if source and identity(source) == source_key:
            matches.append(item)
            continue
        if record.get("type") == "ECSA" and primary_paths:
            result_paths = set()
            for raw_path in _items(_map(item.get("metadata")).get("source_files")):
                path = Path(str(raw_path))
                if path.is_absolute():
                    result_paths.add(identity(path))
                elif source:
                    result_paths.add(identity(Path(source) / path))
            if result_paths and result_paths == primary_paths:
                matches.append(item)
    return matches


def build_project_report_document(
    *, project: Mapping[str, Any], report_data: Mapping[str, Any], generated_at: str | None = None,
) -> dict[str, Any]:
    records = _items(report_data.get("records")) if "records" in report_data else _items(report_data.get("recent_records"))
    project = _map(redact_report_value(project))
    stats = _map(report_data.get("stats"))
    scope = dict(_map(report_data.get("scope"))) or {
        "mode": "supplied_records", "project_id": project.get("id"), "record_count": len(records),
        "run_count": len({str(_map(item).get('run_id')) for item in records if _map(item).get('run_id')}),
        "truncated": None, "scope_status": "旧报告数据：不能确认是否包含全部项目记录",
    }
    summary = [
        _section("统计摘要", fields=[
            ["项目说明", project.get("description")], ["标签", ", ".join(str(item) for item in _items(project.get("tags"))) or "—"],
            ["总记录", stats.get("total_files", stats.get("total", len(records)))], *_scope_fields(scope),
        ]),
    ]
    appendix = [_section("项目与完整选择范围", payload={"project": project, "scope": scope}),
                _section("完整历史记录（保留原始值）", payload=records)]
    figures = []
    recipes: dict[str, Mapping[str, Any]] = {}
    summarized_runs = set()
    normalized_result_count = 0
    for raw_recipe in _items(report_data.get("runs")):
        recipe = _map(raw_recipe)
        if recipe.get("history_partially_deleted"):
            raise ValueError("run has partially deleted history; select remaining record_keys to export")
        run_id = str(recipe.get("run_id") or "")
        recipes[run_id] = recipe
        summarized_runs.add(run_id)
        run_document = build_run_report_document(_manifest_from_recipe(recipe), generated_at=generated_at)
        normalized_result_count += int(run_document["scope"].get("normalized_result_count", 0))
        run_label = f"运行 {len(summarized_runs)} · {_short_id(run_id)}"
        first = run_document["summary"][0]
        summary.append(_section(run_label, fields=[field for field in first["fields"] if field[0] in {"处理时间", "数据类型", "运行状态"}], level=2))
        for block in run_document["summary"][1:]:
            block["level"] = 3
            summary.append(block)
        for block in run_document["appendix"]:
            block["heading"] = run_label + " · " + str(block.get("heading"))
            appendix.append(block)
        for figure in run_document["figures"]:
            figure["caption"] = run_label + " · " + str(figure.get("caption"))
            figures.append(figure)
    if "runs" in report_data:
        scope["normalized_result_count"] = normalized_result_count
        for field in summary[0]["fields"]:
            if field[0] == "运行结果数":
                field[1] = normalized_result_count
        appendix[0]["json"] = redact_report_value({"project": project, "scope": scope})
    excluded = _items(scope.get("excluded_archived_run_ids"))
    excluded_deleted = _items(scope.get("excluded_partially_deleted_run_ids"))
    if excluded:
        summary.append(_section("归档范围说明", paragraphs=[
            "以下运行含归档历史，仅展示未归档记录，不展开完整运行快照及共享图表；勾选包含归档后可导出完整运行。",
            f"涉及 {len(excluded)} 次运行，完整编号见附录。",
        ]))
    if excluded_deleted:
        summary.append(_section("删除范围说明", paragraphs=[
            "以下运行有部分历史记录被删除，仅报告仍存在的历史记录；完整运行快照不再用于恢复已删除结果。",
            f"涉及 {len(excluded_deleted)} 次运行，完整编号见附录。",
        ]))
    for raw in records:
        record = _map(redact_report_value(raw))
        run_id = str(record.get("run_id") or "")
        if run_id in summarized_runs:
            continue  # Its full run metrics/parameters already appear above.
        if run_id not in recipes:
            recipes[run_id] = _load_recipe(run_id) if run_id else {}
        recipe = recipes[run_id]
        params = _record_params(record, recipe)
        sample = _sample_label(record)
        details = [["类型", record.get("type")], ["时间", record.get("timestamp")], ["状态", record.get("status")],
                   ["运行编号", _short_id(run_id)]]
        summary.append(_section(sample, fields=details, level=3))
        summary.append(_section("实验条件与关键参数", fields=_brief_parameters(params),
                                paragraphs=[] if params else ["历史记录未保存参数；实验条件与计算设置不能确认。"], level=3))
        display_metrics = history_metrics_for_display(record)
        summary.append(_section("关键指标", columns=["指标", "数值", "单位"],
            rows=[[item["label"], _display_number(item["value"]), item["unit"] or "—"] for item in display_metrics.values()],
            paragraphs=[] if display_metrics else ["未记录可展示的数值指标；保存的原始结果见附录。"], level=3))
        summary.append(_quality_brief(_map(record.get("quality_summary")), heading="质量摘要"))
        outputs = _items(record.get("output_files"))
        output_block = _section(sample + " · 结果文件", paragraphs=[str(item) for item in outputs], level=3)
        output_block["paragraph_label"] = "结果文件"
        appendix.append(output_block)
        roots = [str(value) for value in (record.get("artifact_root"), recipe.get("output_dir")) if value]
        figure_paths = outputs
        if scope.get("mode") == "record_keys" or run_id in excluded or run_id in excluded_deleted:
            # History output_files may be run-wide. Only result-level artifact
            # associations prove that a chart belongs to this selected sample.
            figure_paths = []
            for result in _record_results(record, recipe):
                figure_paths.extend(_items(result.get("artifacts")))
            if not figure_paths and outputs:
                appendix.append(_section(sample + " · 图表范围", paragraphs=["历史输出清单可能包含整次运行的共享图表，未确认样品归属的图表不嵌入；原始输出位置保留供核对。"], level=3))
        record_figures = _figures(figure_paths, roots)
        for figure in record_figures:
            figure["caption"] = sample + " · " + str(figure["caption"])
        figures.extend(record_figures)
        source_refs = _record_inputs(record, recipe)
        calculation = _map(_map(recipe.get("manifest")).get("calculation"))
        appendix.append(_section(sample + " · 完整保存参数", payload=params, level=3))
        appendix.append(_section(sample + " · 来源与版本", fields=[
            ["运行配方", "已保存" if recipe else "未记录；不能确认可复算性"],
            ["Processing app version", recipe.get("app_version") or _map(_map(recipe.get("manifest")).get("app")).get("version")],
            ["Formula schema", recipe.get("formula_schema_version") or calculation.get("formula_schema_version")],
            ["源数据归档", record.get("source_archive_path") or recipe.get("source_archive_path")],
            ["Source archive SHA-256", recipe.get("source_archive_sha256")], ["Engine", recipe.get("engine")],
            ["Input fingerprints", [{**dict(item), "current_source_status": _source_status(item)} for item in source_refs]],
        ], level=3))
        ir_info = _map(calculation.get("ir_compensation"))
        ir_rows = [item for item in _items(ir_info.get("results")) or _items(ir_info.get("items"))
                   if _map(item).get("lsv_file") == record.get("file_path")]
        if ir_rows:
            appendix.append(_section(sample + " · iR Compensation Provenance", payload={
                **{key: value for key, value in ir_info.items() if key not in {"results", "items"}}, "results": ir_rows,
            }, level=3))
        appendix.extend(_formula_blocks(calculation, prefix=sample + " · "))
    if not records and not _items(report_data.get("runs")):
        summary.append(_section("所选记录", paragraphs=["暂无历史记录"]))
    # Deduplicate shared run charts without dropping their associated captions.
    by_path: dict[str, dict[str, Any]] = {}
    for figure in figures:
        path = str(figure.get("path"))
        if path in by_path:
            by_path[path]["caption"] += "; " + str(figure.get("caption"))
        else:
            by_path[path] = figure
    total_image_bytes = 0
    for figure in by_path.values():
        total_image_bytes += int(figure.get("byte_count", 0))
        if total_image_bytes > _MAX_EMBED_BYTES:
            figure.pop("data_uri", None)
            figure["status"] = "报告图表总量超过嵌入限制；可打开原文件"
    return {
        "title": f"{project.get('name') or 'project'} 项目报告", "subtitle": "可复现项目报告",
        "generated_at": generated_at or datetime.now().isoformat(timespec="seconds"),
        "scope": scope, "summary": summary, "figures": list(by_path.values()), "appendix": appendix,
    }


def render_report_markdown(document: Mapping[str, Any]) -> str:
    """Pure renderer shared by run, project and difference report builders."""
    lines = [f"# {_md(document.get('title'))}", "", _md(document.get("subtitle")), "",
             f"- 生成时间: {_md(document.get('generated_at'))}", ""]

    def append_sections(blocks):
        for raw in _items(blocks):
            block = _map(raw)
            level = 3 if block.get("level") == 3 else 2
            lines.extend(["#" * level + " " + _md(block.get("heading")), ""])
            if block.get("paragraph_label"):
                lines.append("- " + _md(block["paragraph_label"]) + ":")
            for paragraph in _items(block.get("paragraphs")):
                lines.append(("  " if block.get("paragraph_label") else "") + "- " + _md(paragraph))
            if block.get("field_label"):
                lines.append("- " + _md(block["field_label"]) + ":")
            for field in _items(block.get("fields")):
                if isinstance(field, (list, tuple)) and len(field) == 2:
                    lines.append(("  " if block.get("field_label") else "") + f"- {_md(field[0])}: {_md(field[1])}")
            columns = _items(block.get("columns"))
            if columns:
                lines.extend(["", "| " + " | ".join(_md(item) for item in columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"])
                for row in _items(block.get("rows")):
                    lines.append("| " + " | ".join(_md(item) for item in _items(row)) + " |")
            if "json" in block:
                payload = json.dumps(redact_report_value(block["json"]), ensure_ascii=False, indent=2, default=str)
                fence = "`" * max(3, max((len(item) + 1 for item in re.findall(r"`+", payload)), default=3))
                lines.extend(["", fence + "json", payload, fence])
            lines.append("")

    append_sections(document.get("summary"))
    lines.extend(["## 主要图表 / Figures", ""])
    for raw in _items(document.get("figures")):
        figure = _map(raw)
        caption = _md(figure.get("caption"))
        href = _safe_href(figure.get("markdown_href")) or _safe_href(figure.get("href"))
        if href:
            prefix = "!" if _safe_image_uri(figure.get("data_uri")) else ""
            lines.extend([f"{prefix}[{caption}](<{href}>)", ""])
        lines.extend([f"- {caption}: {_md(figure.get('status'))}", ""])
    if not _items(document.get("figures")):
        lines.extend(["- 未记录可用图表。", ""])
    lines.extend(["## 复现附录 / Reproducibility Appendix", ""])
    lines.extend(["- 正文数值最多显示 6 位有效数字；以下保存的原始结果保留完整精度。", ""])
    append_sections(document.get("appendix"))
    if _items(document.get("figures")):
        lines.extend(["### 图表来源路径", ""])
        lines.extend(f"- {_md(_map(item).get('path'))}" for item in _items(document.get("figures")))
    return "\n".join(lines)


def render_report_html(document: Mapping[str, Any]) -> str:
    """Pure HTML renderer: every text value is escaped; scripts/SVG are excluded."""
    def text(value):
        return escape(_text(value), quote=True)

    def sections(blocks):
        parts = []
        for raw in _items(blocks):
            block = _map(raw)
            heading = "h3" if block.get("level") == 3 else "h2"
            parts.append(f"<section><{heading}>{text(block.get('heading'))}</{heading}>")
            for paragraph in _items(block.get("paragraphs")):
                parts.append(f"<p>{text(paragraph)}</p>")
            if block.get("fields"):
                parts.append("<dl>")
                for field in _items(block.get("fields")):
                    if isinstance(field, (list, tuple)) and len(field) == 2:
                        parts.append(f"<div><dt>{text(field[0])}</dt><dd>{text(field[1])}</dd></div>")
                parts.append("</dl>")
            columns = _items(block.get("columns"))
            if columns:
                parts.append("<div class='table-scroll'><table><thead><tr>" + "".join(f"<th>{text(item)}</th>" for item in columns) + "</tr></thead><tbody>")
                for row in _items(block.get("rows")):
                    parts.append("<tr>" + "".join(f"<td>{text(item)}</td>" for item in _items(row)) + "</tr>")
                parts.append("</tbody></table></div>")
            if "json" in block:
                payload = json.dumps(redact_report_value(block["json"]), ensure_ascii=False, indent=2, default=str)
                parts.append(f"<pre>{escape(payload)}</pre>")
            parts.append("</section>")
        return "\n".join(parts)

    figures = []
    for raw in _items(document.get("figures")):
        figure = _map(raw)
        uri = _safe_image_uri(figure.get("data_uri"))
        href = _safe_href(figure.get("href"))
        figures.append("<figure>")
        if uri:
            figures.append(f'<img src="{escape(uri, quote=True)}" alt="{text(figure.get("caption"))}">')
        elif href:
            figures.append(f'<a href="{escape(href, quote=True)}">打开已验证位置的图表</a>')
        figures.append(f"<figcaption>{text(figure.get('caption'))} — {text(figure.get('status'))}</figcaption></figure>")
    return """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>""" + text(document.get("title")) + """</title><style>
body{margin:0;background:#f3f6f8;color:#173144;font:15px/1.65 system-ui,'Microsoft YaHei',sans-serif}
main{max-width:1120px;margin:32px auto;padding:0 20px}header,section,figure{background:white;padding:18px;margin:0 0 12px;border:1px solid #d2dee5;border-radius:8px}
h1,h2,h3{line-height:1.3}h1{font-size:30px}h2{font-size:22px}h3{font-size:18px}dl{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}dt{font-weight:600}dd{margin:4px 0;overflow-wrap:anywhere}table{border-collapse:collapse;width:100%}th,td{padding:9px;border:1px solid #d2dee5;text-align:left;overflow-wrap:anywhere}th{background:#eaf1f5}.table-scroll{overflow:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f6f8;padding:16px;font:12px/1.6 monospace}img{max-width:100%;height:auto}figcaption{color:#526675}a{color:#0b665f}nav{display:flex;gap:24px}@media print{body{background:white}main{margin:0;max-width:none}section,figure{break-inside:avoid}nav{display:none}}
</style></head><body><main><header><h1>""" + text(document.get("title")) + "</h1><p>" + text(document.get("subtitle")) + "</p><p>生成时间: " + text(document.get("generated_at")) + "</p><nav><a href='#figures'>查看图表</a><a href='#appendix'>查看复现附录</a></nav></header>" + sections(document.get("summary")) + "<h2 id='figures'>主要图表 / Figures</h2>" + ("\n".join(figures) or "<p>未记录可用图表。</p>") + "<h2 id='appendix'>复现附录 / Reproducibility Appendix</h2><p>正文数值最多显示 6 位有效数字；以下保存的原始结果保留完整精度。</p>" + sections(document.get("appendix")) + "</main></body></html>"


def export_report_document(document: Mapping[str, Any], *, output_dir: str, stem: str, format: str = "html") -> dict[str, Any]:
    """Export both formats; copy verified images so Markdown remains portable."""
    if format not in {"html", "markdown"}:
        return {"status": "error", "message": "format must be html or markdown"}
    if not stem or Path(stem).name != stem or any(ch in stem for ch in '/\\:*?"<>|'):
        raise ValueError("report filename must be a plain local filename")
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    document = deepcopy(dict(document))
    for figure in _items(document.get("figures")):
        uri = _safe_image_uri(_map(figure).get("data_uri"))
        if not uri:
            continue
        mime, encoded = uri.split(";base64,", 1)
        content = base64.b64decode(encoded, validate=True)
        suffix = {"data:image/png": "png", "data:image/jpeg": "jpg", "data:image/gif": "gif", "data:image/webp": "webp"}[mime]
        # Use a separate ASCII-only stem for link safety even for CJK titles.
        asset_dir = "report_" + hashlib.sha256(stem.encode("utf-8")).hexdigest()[:12] + "_assets"
        relative = f"{asset_dir}/{hashlib.sha256(content).hexdigest()}.{suffix}"
        asset = root / relative
        asset.parent.mkdir(exist_ok=True)
        asset.write_bytes(content)
        figure["markdown_href"] = quote(relative)
    markdown_path, html_path = root / (stem + ".md"), root / (stem + ".html")
    markdown_path.write_text(render_report_markdown(document), encoding="utf-8")
    html_path.write_text(render_report_html(document), encoding="utf-8")
    selected = html_path if format == "html" else markdown_path
    return {
        "status": "success", "path": str(selected), "file_name": selected.name,
        "markdown_path": str(markdown_path), "html_path": str(html_path), "scope": document.get("scope", {}),
    }


def export_run_report(run_id: str, *, output_dir: str, format: str = "html") -> dict[str, Any]:
    recipe = _load_recipe(str(run_id or "").strip())
    if not recipe:
        return {"status": "error", "message": "run recipe not found; cannot reconstruct unrecorded run settings"}
    if recipe.get("history_partially_deleted"):
        return {"status": "error", "message": "run has partially deleted history; select remaining record_keys to export"}
    manifest = _manifest_from_recipe(recipe)
    document = build_run_report_document(manifest)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return export_report_document(document, output_dir=output_dir, stem=f"run_report_{stamp}", format=format)
