"""Project replicate groups and downloadable statistics/plots."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from electrochem_v6.core.replicate_service import (
    export_replicates_csv,
    get_replicates,
    list_replicates,
    preview_replicates,
    replicate_metric_svg,
    save_replicates,
)
from electrochem_v6.server.request_utils import read_json
from electrochem_v6.store.replicate_groups import delete_replicate_group


def _parts(handler: Any) -> list[str]:
    return [unquote(part) for part in urlparse(handler.path).path.strip("/").split("/")]


def dispatch_replicates_get(handler: Any) -> bool:
    parts = _parts(handler)
    project_list = len(parts) == 5 and parts[:3] == ["api", "v1", "projects"] and parts[4] == "replicate-groups"
    group_route = len(parts) in {4, 5} and parts[:3] == ["api", "v1", "replicate-groups"]
    if not project_list and not group_route:
        return False
    if group_route and len(parts) == 5 and parts[4] != "export":
        return False
    try:
        if project_list:
            handler._send_json(200, {"status": "success", "groups": list_replicates(parts[3])})
        else:
            group = get_replicates(parts[3])
            if len(parts) == 4:
                handler._send_json(200, {"status": "success", "group": group})
            else:
                query = parse_qs(urlparse(handler.path).query)
                format_name = query.get("format", ["csv"])[0]
                if format_name == "csv":
                    body, content_type = export_replicates_csv(group), "text/csv; charset=utf-8"
                elif format_name == "svg":
                    body = replicate_metric_svg(group, query.get("metric", [""])[0]).encode("utf-8")
                    content_type = "image/svg+xml; charset=utf-8"
                else:
                    raise ValueError("format 仅支持 csv 或 svg")
                handler.send_response(200)
                handler.send_header("Content-Type", content_type)
                handler.send_header("Content-Length", str(len(body)))
                handler.send_header("Content-Disposition", f'attachment; filename="replicates.{format_name}"')
                handler.send_header("X-Content-Type-Options", "nosniff")
                handler.send_header("Cache-Control", "no-store")
                handler.end_headers()
                handler.wfile.write(body)
    except LookupError as exc:
        handler._send_json(404, {"status": "error", "message": str(exc)})
    except ValueError as exc:
        handler._send_json(400, {"status": "error", "message": str(exc)})
    return True


def dispatch_replicates_post(handler: Any, manager: Any = None) -> bool:
    parts = _parts(handler)
    project_route = len(parts) == 5 and parts[:3] == ["api", "v1", "projects"] and parts[4] in {"replicate-groups", "replicate-preview"}
    group_route = len(parts) == 5 and parts[:3] == ["api", "v1", "replicate-groups"] and parts[4] in {"update", "delete"}
    if not project_route and not group_route:
        return False
    try:
        payload = read_json(handler, handler.MAX_JSON_BODY_BYTES)
        if project_route:
            group = preview_replicates(parts[3], payload) if parts[4] == "replicate-preview" else save_replicates(parts[3], payload)
            handler._send_json(200, {"status": "success", "group": group})
        else:
            group = get_replicates(parts[3])
            if parts[4] == "delete":
                delete_replicate_group(parts[3])
                handler._send_json(200, {"status": "success"})
            else:
                result = save_replicates(group["project_id"], payload, group_id=parts[3])
                handler._send_json(200, {"status": "success", "group": result})
    except LookupError as exc:
        handler._send_json(404, {"status": "error", "message": str(exc)})
    except ValueError as exc:
        handler._send_json(400, {"status": "error", "message": str(exc)})
    return True
