"""HTTP request and upload safety helpers for v6 server."""

from __future__ import annotations

import json
import os
import zipfile
from email.parser import BytesParser
from email.policy import default
from typing import Any, Dict, Tuple


def read_body_with_limit(handler: Any, max_bytes: int) -> bytes:
    raw_length = handler.headers.get("Content-Length") or "0"
    try:
        length = int(raw_length)
    except ValueError as exc:
        raise ValueError("Content-Length 非法") from exc
    if length < 0:
        raise ValueError("请求体长度非法")
    if length > max_bytes:
        raise ValueError(f"请求体过大，最大支持 {max_bytes // (1024 * 1024)}MB")
    return handler.rfile.read(length) if length > 0 else b""


def read_json(handler: Any, max_json_body_bytes: int) -> Dict[str, Any]:
    body = read_body_with_limit(handler, max_json_body_bytes)
    if not body.strip():
        return {}
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("请求体不是合法的 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("JSON ??????????")
    return payload


def parse_multipart_form(body: bytes, content_type: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    if "multipart/form-data" not in content_type:
        raise ValueError("Content-Type 必须为 multipart/form-data")
    boundary = None
    for part in content_type.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            boundary = part.split("=", 1)[1].strip().strip('"')
            break
    if not boundary:
        raise ValueError("缺少 multipart boundary")

    raw = b"Content-Type: " + content_type.encode("utf-8") + b"\r\n\r\n" + body
    msg = BytesParser(policy=default).parsebytes(raw)
    fields: Dict[str, Any] = {}
    files: Dict[str, Any] = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        filename = part.get_filename()
        if filename:
            files[name] = part
        else:
            fields[name] = part.get_content()
    return fields, files


def write_uploaded_zip(file_item: Any, zip_path: str, max_upload_file_bytes: int) -> None:
    payload = file_item.get_payload(decode=True)
    if payload is None:
        raise ValueError("上传文件为空")
    if len(payload) > max_upload_file_bytes:
        raise ValueError(f"上传 ZIP 过大，最大支持 {max_upload_file_bytes // (1024 * 1024)}MB")
    with open(zip_path, "wb") as f:
        f.write(payload)


def extract_zip_safely(
    zip_path: str,
    extract_dir: str,
    *,
    max_zip_files: int,
    max_zip_uncompressed_bytes: int,
) -> None:
    with zipfile.ZipFile(zip_path, "r") as archive:
        infos = archive.infolist()
        if len(infos) > max_zip_files:
            raise ValueError(f"ZIP 文件过多，最多允许 {max_zip_files} 个条目")
        total_size = 0
        base_dir = os.path.abspath(extract_dir)
        for info in infos:
            name = info.filename or ""
            if not name:
                continue
            normalized = os.path.normpath(name).replace("\\", "/")
            if normalized.startswith("/") or normalized.startswith("../") or normalized.startswith(".."):
                raise ValueError("ZIP 包含非法路径")
            target_path = os.path.abspath(os.path.join(extract_dir, normalized))
            try:
                if os.path.commonpath([base_dir, target_path]) != base_dir:
                    raise ValueError("ZIP 包含越界路径")
            except ValueError as exc:
                raise ValueError("ZIP 包含越界路径") from exc
            if info.is_dir():
                continue
            total_size += max(0, int(info.file_size or 0))
            if total_size > max_zip_uncompressed_bytes:
                raise ValueError("ZIP 解压后体积过大，已超出限制")
        archive.extractall(extract_dir)


def path_parts(path: str) -> list[str]:
    return [p for p in path.strip("/").split("/") if p]
