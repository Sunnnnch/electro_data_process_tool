import io
import json
import os
import re
import socket
import time
import uuid
import zipfile
from pathlib import Path
from urllib import error, request

import pytest

import electrochem_v6.core.process_service as process_service  # noqa: E402
import electrochem_v6.server.routes_get as routes_get  # noqa: E402
import electrochem_v6.server.routes_post as routes_post  # noqa: E402
from electrochem_v6.core.processing_scan import matches_named_file  # noqa: E402
from electrochem_v6.server import V6ServerManager  # noqa: E402
from electrochem_v6.store.conversations import append_message, get_conversation  # noqa: E402
from electrochem_v6.store.history import attach_run_outputs  # noqa: E402
from electrochem_v6.store.runtime import get_history_store, reset_runtime  # noqa: E402


def test_v6_background_process_job_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "job-runtime"))
    reset_runtime()
    port = _get_free_port()
    manager = V6ServerManager(port=port)
    ok, _ = manager.start()
    assert ok
    try:
        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/process/jobs",
            method="POST",
            payload={"folder_path": str(tmp_path / "missing"), "data_types": ["LSV"]},
        )
        assert status == 202
        job_id = payload.get("job_id")
        assert job_id

        job = None
        for _ in range(100):
            status, detail = _read(f"http://127.0.0.1:{port}/api/v1/process/jobs/{job_id}")
            assert status == 200
            job = detail.get("job")
            if job and job.get("status") in {"failed", "succeeded", "cancelled"}:
                break
            time.sleep(0.02)
        assert job and job.get("status") == "failed"
        assert "不存在" in str(job.get("error"))

        status, listing = _read(f"http://127.0.0.1:{port}/api/v1/process/jobs?limit=10")
        assert status == 200
        assert any(item.get("job_id") == job_id for item in listing.get("jobs") or [])
    finally:
        manager.stop()
        reset_runtime()


def _get_free_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    _, port = sock.getsockname()
    sock.close()
    return port


def _read(url, method="GET", payload=None, headers=None):
    data = None
    hdr = headers or {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        hdr.setdefault("Content-Type", "application/json")
    req = request.Request(url, method=method, data=data, headers=hdr)
    try:
        with request.urlopen(req, timeout=4) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            try:
                parsed = json.loads(body)
            except Exception:
                parsed = {"raw": body}
            return resp.status, parsed
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"raw": body}
        return exc.code, parsed


def _read_raw(url, method="POST", data=None, headers=None):
    req = request.Request(url, method=method, data=data, headers=headers or {})
    try:
        with request.urlopen(req, timeout=4) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            try:
                parsed = json.loads(body)
            except Exception:
                parsed = {"raw": body}
            return resp.status, parsed
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"raw": body}
        return exc.code, parsed


def _build_multipart(fields, files):
    boundary = f"----v6boundary{uuid.uuid4().hex[:8]}"
    chunks = []
    for key, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        chunks.append(f"{value}\r\n".encode("utf-8"))
    for item in files:
        # (field_name, filename, content_bytes, content_type)
        field_name, filename, content, content_type = item
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode("utf-8")
        )
        chunks.append(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        chunks.append(content)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(chunks)
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    return body, headers


def test_v6_ui_manual_static_files():
    port = _get_free_port()
    manager = V6ServerManager(port=port)
    ok, _ = manager.start()
    assert ok
    try:
        status, payload = _read(f"http://127.0.0.1:{port}/ui/static/help_manual.zh.md")
        assert status == 200
        assert "智能电化学数据处理软件" in payload.get("raw", "")
        assert "## 快速上手" in payload.get("raw", "")

        status, payload = _read(f"http://127.0.0.1:{port}/ui/static/help_manual.en.md")
        assert status == 200
        assert "Intelligent Electrochemical Data Processing Software" in payload.get("raw", "")
        assert "## Quick start" in payload.get("raw", "")
    finally:
        manager.stop()


def test_v6_ui_injects_per_launch_session_token():
    port = _get_free_port()
    manager = V6ServerManager(port=port)
    ok, _ = manager.start()
    assert ok
    try:
        status, payload = _read(f"http://127.0.0.1:{port}/ui")
        html = payload.get("raw", "")
        assert status == 200
        assert "__ELECTROCHEM_SESSION_TOKEN__" not in html
        match = re.search(r'name="electrochem-session-token" content="([^"]+)"', html)
        assert match is not None
        assert match.group(1) == manager.session_token
    finally:
        manager.stop()


def test_v6_server_rejects_cross_site_browser_post_and_accepts_ui_token():
    port = _get_free_port()
    manager = V6ServerManager(port=port)
    ok, _ = manager.start()
    assert ok
    try:
        url = f"http://127.0.0.1:{port}/api/v1/process"
        status, _payload = _read(
            url,
            method="POST",
            payload={"folder_path": "__missing__", "data_types": ["LSV"]},
            headers={"Origin": "https://malicious.example", "Sec-Fetch-Site": "cross-site"},
        )
        assert status == 403

        status, payload = _read(
            url,
            method="POST",
            payload={"folder_path": "__missing__", "data_types": ["LSV"]},
            headers={
                "Origin": f"http://127.0.0.1:{port}",
                "Sec-Fetch-Site": "same-origin",
                "X-Electrochem-Session": manager.session_token,
            },
        )
        assert status == 400
        assert payload.get("status") == "error"
    finally:
        manager.stop()


def test_v6_json_route_rejects_text_plain_payload():
    port = _get_free_port()
    manager = V6ServerManager(port=port)
    ok, _ = manager.start()
    assert ok
    try:
        status, payload = _read_raw(
            f"http://127.0.0.1:{port}/api/v1/process",
            data=b"{}",
            headers={"Content-Type": "text/plain"},
        )
        assert status == 400
        assert "application/json" in payload.get("message", "")
    finally:
        manager.stop()


def test_processing_core_filename_match_strategies():
    assert matches_named_file("LSV_sample01.csv", "prefix", "LSV") is True
    assert matches_named_file("sample_LSV_01.csv", "contains", "LSV") is True
    assert matches_named_file("sample_LSV_01.csv", "contains", "EIS") is False
    assert matches_named_file("sample-12-cv.txt", "regex", r"sample-\d+-cv") is True
    assert matches_named_file("sample-12-cv.txt", "regex", r"sample-(") is False


def test_v6_process_modules_catalog_route():
    port = _get_free_port()
    manager = V6ServerManager(port=port)
    ok, _ = manager.start()
    assert ok
    try:
        status, payload = _read(f"http://127.0.0.1:{port}/api/v1/process/modules?data_types=LSV,FE")
        assert status == 200
        assert payload.get("status") == "success", payload
        catalog = payload.get("catalog") or {}
        modules = {item["key"]: item for item in catalog.get("modules") or []}
        assert list(modules) == ["LSV", "COUPLED"]
        assert modules["LSV"]["origin"] == "builtin"
        assert modules["LSV"]["runner"] == {"kind": "module", "available": True}
        assert modules["COUPLED"]["runner"] == {"kind": "module", "available": True}
        assert modules["COUPLED"]["display_name"] == "COUPLED/FE"

        status, payload = _read(f"http://127.0.0.1:{port}/api/v1/process/modules?data_types=UNKNOWN")
        assert status == 400
        assert payload.get("status") == "error"
    finally:
        manager.stop()


def test_v6_health_and_ui_static():
    port = _get_free_port()
    manager = V6ServerManager(port=port)
    ok, _ = manager.start()
    assert ok
    try:
        status, payload = _read(f"http://127.0.0.1:{port}/health")
        assert status == 200
        assert payload.get("status") == "ok"

        status, payload = _read(f"http://127.0.0.1:{port}/ui")
        assert status == 200
        ui_html = payload.get("raw", "")
        assert "<title>ElectroChem｜智能电化学数据处理软件</title>" in ui_html
        static_scripts = [
            "/ui/static/theme.js",
            "/ui/static/i18n.js",
            "/ui/static/api.js",
            "/ui/static/appearance.js",
            "/ui/static/chart_preview.js",
            "/ui/static/process_schema.js",
            "/ui/static/process_source_selection.js",
            "/ui/static/preflight_model.js",
            "/ui/static/project_compare_model.js",
            "/ui/static/process_result_model.js",
            "/ui/static/assistant_context.js",
            "/ui/static/assistant_prompt.js",
            "/ui/static/assistant_api.js",
            "/ui/static/llm_api.js",
            "/ui/static/project_api.js",
            "/ui/static/system_api.js",
            "/ui/static/processing_api.js",
            "/ui/static/app.js",
        ]
        script_positions = [ui_html.index(path) for path in static_scripts]
        assert script_positions == sorted(script_positions)
        assert script_positions[0] < ui_html.index('/ui/static/styles.css')

        status, payload = _read(f"http://127.0.0.1:{port}/ui/static/styles.css")
        assert status == 200
        assert "--bg-a" in payload.get("raw", "")

        static_globals = {
            "/ui/static/api.js": "window.ElectrochemApi",
            "/ui/static/theme.js": "window.ElectrochemTheme",
            "/ui/static/process_schema.js": "window.ElectrochemProcessingSchema",
            "/ui/static/process_source_selection.js": "window.ElectrochemProcessSourceSelection",
            "/ui/static/preflight_model.js": "window.ElectrochemPreflightModel",
            "/ui/static/project_compare_model.js": "window.ElectrochemProjectCompareModel",
            "/ui/static/process_result_model.js": "window.ElectrochemProcessResultModel",
            "/ui/static/assistant_context.js": "window.ElectrochemAssistantContext",
            "/ui/static/assistant_prompt.js": "window.ElectrochemAssistantPrompt",
            "/ui/static/assistant_api.js": "window.ElectrochemAssistantApi",
            "/ui/static/llm_api.js": "window.ElectrochemLLMApi",
            "/ui/static/project_api.js": "window.ElectrochemProjectApi",
            "/ui/static/system_api.js": "window.ElectrochemSystemApi",
            "/ui/static/processing_api.js": "window.ElectrochemProcessingApi",
        }
        for path, expected_global in static_globals.items():
            status, payload = _read(f"http://127.0.0.1:{port}{path}")
            assert status == 200
            assert expected_global in payload.get("raw", "")

        status, payload = _read(f"http://127.0.0.1:{port}/ui/static/coupled_template_charge.csv")
        assert status == 200
        assert "sample,product,product_moles,n,charge" in payload.get("raw", "")

        status, payload = _read(f"http://127.0.0.1:{port}/ui/static/coupled_template_current_time.csv")
        assert status == 200
        assert "sample,product,product_moles,n,current_mA,time_s" in payload.get("raw", "")
    finally:
        manager.stop()


def test_v6_projects_and_process_route():
    port = _get_free_port()
    manager = V6ServerManager(port=port)
    ok, _ = manager.start()
    assert ok
    try:
        status, payload = _read(f"http://127.0.0.1:{port}/api/v1/projects")
        assert status == 200
        assert payload.get("status") == "success"

        name = f"v6_test_{uuid.uuid4().hex[:8]}"
        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/projects",
            method="POST",
            payload={"name": name, "description": "v6 test"},
        )
        assert status == 200
        assert payload.get("status") == "success"
        assert payload.get("project", {}).get("name") == name
        project_id = payload.get("project_id")
        assert project_id

        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/projects/{project_id}/update",
            method="POST",
            payload={
                "name": f"{name}_edited",
                "description": "edited from test",
                "tags": ["alpha", "beta"],
                "color": "#123456",
            },
        )
        assert status == 200
        assert payload.get("status") == "success"
        assert payload.get("project", {}).get("name") == f"{name}_edited"
        assert payload.get("project", {}).get("description") == "edited from test"
        assert payload.get("project", {}).get("tags") == ["alpha", "beta"]
        assert payload.get("project", {}).get("color") == "#123456"

        sample_name = f"sample_{uuid.uuid4().hex[:8]}"
        get_history_store().add_record(
            {
                "timestamp": "2026-08-27 10:00:00",
                "type": "LSV",
                "file_path": f"D:/raw/{sample_name}.txt",
                "file_name": f"{sample_name}.txt",
                "sample_name": sample_name,
                "project_id": project_id,
                "run_id": f"run_{uuid.uuid4().hex[:8]}",
                "status": "success",
                "results": {},
            }
        )
        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/projects/{project_id}/samples"
        )
        assert status == 200
        sample = next(item for item in payload.get("samples") or [] if item.get("name") == sample_name)
        assert sample.get("data_count") == 1

        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/projects/{project_id}/samples/{sample['id']}/update",
            method="POST",
            payload={"note": "0.5 M KOH", "tags": ["对照组", "复测"]},
        )
        assert status == 200
        assert payload.get("sample", {}).get("note") == "0.5 M KOH"
        assert payload.get("sample", {}).get("tags") == ["对照组", "复测"]

        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/history?project={project_id}"
        )
        assert status == 200
        linked = next(item for item in payload.get("records") or [] if item.get("sample_name") == sample_name)
        assert linked.get("sample_note") == "0.5 M KOH"
        assert linked.get("sample_tags") == ["对照组", "复测"]

        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/projects/{project_id}/delete",
            method="POST",
            payload={},
        )
        assert status == 200
        assert payload.get("message") == "project archived"
        status, payload = _read(f"http://127.0.0.1:{port}/api/v1/projects?status=archived")
        assert any(item.get("id") == project_id for item in payload.get("projects") or [])

        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/projects/{project_id}/restore",
            method="POST",
            payload={},
        )
        assert status == 200
        assert payload.get("status") == "success"

        _read(
            f"http://127.0.0.1:{port}/api/v1/projects/{project_id}/delete",
            method="POST",
            payload={},
        )
        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/projects/{project_id}/delete-permanent",
            method="POST",
            payload={"delete_artifacts": True},
        )
        assert status == 200
        assert payload.get("deleted", {}).get("projects") == 1

        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/process",
            method="POST",
            payload={"folder_path": "__not_exists__", "data_type": "LSV"},
        )
        assert status == 400
        assert payload.get("status") == "error"
    finally:
        manager.stop()


def test_v6_process_route_accepts_data_types_list(monkeypatch):
    port = _get_free_port()
    manager = V6ServerManager(port=port)
    ok, _ = manager.start()
    assert ok
    try:
        captured = {}

        def _fake_process_folder(payload):
            captured["payload"] = payload
            return {
                "status": "success",
                "result": {
                    "summary": "multi-type ok",
                    "data_type": "LSV",
                    "data_types": ["LSV", "CV"],
                    "processing": {"output_files": ["LSV_results.csv", "CV_results.csv"]},
                },
            }

        monkeypatch.setattr(routes_post, "process_folder", _fake_process_folder)
        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/process",
            method="POST",
            payload={"folder_path": "D:/mock", "data_types": ["LSV", "CV"]},
        )
        assert status == 200
        assert payload.get("status") == "success"
        assert payload.get("result", {}).get("data_types") == ["LSV", "CV"]
        assert captured.get("payload", {}).get("data_types") == ["LSV", "CV"]
    finally:
        manager.stop()


def test_v6_process_route_rejects_non_object_json():
    port = _get_free_port()
    manager = V6ServerManager(port=port)
    ok, _ = manager.start()
    assert ok
    try:
        status, payload = _read_raw(
            f"http://127.0.0.1:{port}/api/v1/process",
            data=b"[]",
            headers={"Content-Type": "application/json"},
        )
        assert status == 400
        assert payload.get("status") == "error"
    finally:
        manager.stop()


def test_v6_process_route_rejects_invalid_numeric_params(tmp_path):
    port = _get_free_port()
    manager = V6ServerManager(port=port)
    ok, _ = manager.start()
    assert ok
    try:
        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/process",
            method="POST",
            payload={
                "folder_path": str(tmp_path),
                "data_types": ["LSV"],
                "params": {"font_size": "abc"},
            },
        )
        assert status == 400
        assert payload.get("status") == "error"
        assert "font_size" in str(payload.get("message", ""))
    finally:
        manager.stop()


def test_v6_process_route_requires_eq_potential_when_overpotential_enabled(tmp_path):
    port = _get_free_port()
    manager = V6ServerManager(port=port)
    ok, _ = manager.start()
    assert ok
    try:
        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/process",
            method="POST",
            payload={
                "folder_path": str(tmp_path),
                "data_types": ["LSV"],
                "params": {"overpotential_enabled": True},
            },
        )
        assert status == 400
        assert payload.get("status") == "error"
        assert "eq_potential" in str(payload.get("message", ""))
    finally:
        manager.stop()


def test_v6_process_folder_calculates_rhe_offset_from_formula(tmp_path, monkeypatch):
    data_dir = tmp_path / "rhe_case"
    data_dir.mkdir()
    (data_dir / "LSV_demo.txt").write_text("Potential Current\n0 0\n1 0.001\n2 0.002\n", encoding="utf-8")
    output_csv = data_dir / "LSV_results.csv"
    output_csv.write_text("sample,file\nsample,LSV_demo\n", encoding="utf-8")
    captured = {}

    def _fake_run_modules(folder_path, gui_vars, callbacks=None, resolve_start_line=None):
        captured["folder_path"] = folder_path
        captured["gui_vars"] = dict(gui_vars)
        return {"lsv_csv": str(output_csv), "summary_path": "", "messages": [], "quality_summary": {}}

    monkeypatch.setattr(process_service, "_run_selected_modules", _fake_run_modules)
    monkeypatch.setattr(process_service, "attach_run_outputs", lambda **_kwargs: {"status": "success", "updated": 0})
    payload = process_service.process_folder(
        {
            "folder_path": str(data_dir),
            "data_type": "LSV",
            "params": {
                "potential_mode": "formula_rhe",
                "rhe_ph": 13.6,
                "reference_electrode_preset": "agcl_sat_kcl",
                "reference_electrode_potential": 0.197,
            },
        }
    )
    assert payload.get("status") == "success"
    assert captured.get("gui_vars", {}).get("potential_mode") == "formula_rhe"
    slope = 2.303 * 8.31446261815324 * (25.0 + 273.15) / 96485.33212
    assert captured.get("gui_vars", {}).get("potential_offset") == pytest.approx(0.197 + slope * 13.6, rel=1e-9)
    conversion = captured.get("gui_vars", {}).get("potential_conversion", {})
    assert conversion.get("temperature_c") == pytest.approx(25.0)
    assert conversion.get("nernst_slope_v_per_ph") == pytest.approx(slope)
    run_report_path = payload.get("result", {}).get("manifest", {}).get("outputs", {}).get("run_report_path")
    assert run_report_path and os.path.exists(run_report_path)
    assert "2.303 * R * T / F" in open(run_report_path, encoding="utf-8").read()


def test_v6_system_select_folder(monkeypatch):
    port = _get_free_port()
    manager = V6ServerManager(port=port)
    ok, _ = manager.start()
    assert ok
    try:
        def _fake_select_folder_dialog(initial_dir=None):
            return {"status": "success", "folder_path": initial_dir or "D:/mock_data"}

        monkeypatch.setattr(routes_post, "select_folder_dialog", _fake_select_folder_dialog)

        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/system/select-folder",
            method="POST",
            payload={"initial_dir": "D:/demo"},
        )
        assert status == 200
        assert payload.get("status") == "success"
        assert payload.get("folder_path") == "D:/demo"
    finally:
        manager.stop()


def test_v6_system_select_file(monkeypatch):
    port = _get_free_port()
    manager = V6ServerManager(port=port)
    ok, _ = manager.start()
    assert ok
    try:
        def _fake_select_file_dialog(initial_path=None, extensions=None):
            return {
                "status": "success",
                "file_path": initial_path or "D:/mock_data/EIS.txt",
                "extensions": extensions,
            }

        monkeypatch.setattr(routes_post, "select_file_dialog", _fake_select_file_dialog)

        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/system/select-file",
            method="POST",
            payload={"initial_path": "D:/demo/EIS.csv", "extensions": [".txt", ".csv"]},
        )
        assert status == 200
        assert payload.get("status") == "success"
        assert payload.get("file_path") == "D:/demo/EIS.csv"
        assert payload.get("extensions") == [".txt", ".csv"]
    finally:
        manager.stop()


def test_v6_system_select_files(monkeypatch):
    port = _get_free_port()
    manager = V6ServerManager(port=port)
    ok, _ = manager.start()
    assert ok
    try:
        def _fake_select_files_dialog(initial_path=None, extensions=None):
            return {
                "status": "success",
                "file_paths": ["D:/demo/LSV_A.txt", "D:/demo/LSV_B.csv"],
                "count": 2,
                "extensions": extensions,
            }

        monkeypatch.setattr(routes_post, "select_files_dialog", _fake_select_files_dialog)
        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/system/select-files",
            method="POST",
            payload={"initial_path": "D:/demo", "extensions": [".txt", ".csv"]},
        )

        assert status == 200
        assert payload.get("status") == "success"
        assert payload.get("count") == 2
        assert payload.get("file_paths") == ["D:/demo/LSV_A.txt", "D:/demo/LSV_B.csv"]
    finally:
        manager.stop()


def test_v6_system_open_path(monkeypatch):
    port = _get_free_port()
    manager = V6ServerManager(port=port)
    ok, _ = manager.start()
    assert ok
    try:
        monkeypatch.setattr(
            routes_post,
            "open_path_target",
            lambda path_value=None, reveal_only=False: {
                "status": "success",
                "opened": path_value,
                "reveal_only": reveal_only,
            },
        )
        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/system/open-path",
            method="POST",
            payload={"path": "D:/mock/result.png", "reveal_only": True},
        )
        assert status == 200
        assert payload.get("status") == "success"
        assert payload.get("opened") == "D:/mock/result.png"
        assert payload.get("reveal_only") is True
    finally:
        manager.stop()


def test_v6_project_compare_plot_route(tmp_path, monkeypatch):
    old_projects = os.environ.get("ELECTROCHEM_V6_PROJECTS_FILE")
    old_history = os.environ.get("ELECTROCHEM_V6_HISTORY_FILE")
    old_conv = os.environ.get("ELECTROCHEM_V6_CONVERSATION_FILE")
    try:
        os.environ["ELECTROCHEM_V6_PROJECTS_FILE"] = str(tmp_path / "projects.json")
        os.environ["ELECTROCHEM_V6_HISTORY_FILE"] = str(tmp_path / "history.json")
        os.environ["ELECTROCHEM_V6_CONVERSATION_FILE"] = str(tmp_path / "conversation.json")
        monkeypatch.setattr(process_service.os, "getcwd", lambda: str(tmp_path))

        hist = get_history_store()
        hist.add_record(
            {
                "timestamp": "2026-02-28 18:00:00",
                "sample_name": "sample_a",
                "file_name": "LSV_a",
                "file_path": str(tmp_path / "sample_a.txt"),
                "type": "LSV",
                "status": "success",
                "project_id": "proj_compare",
                "project_name": "Compare Demo",
                "results": {
                    "overpotential_10": 321.0,
                    "overpotential_at_10.0": 321.0,
                    "overpotential_at_50.0": 412.0,
                    "potential_10": 0.401,
                    "potential_at_10.0": 0.401,
                    "potential_at_50.0": 0.463,
                    "tafel_slope": 88.0,
                },
            },
            data={
                "potential_original": [-0.25, -0.2, -0.15, -0.1],
                "potential_compensated": [-0.24, -0.19, -0.14, -0.09],
                "current": [1.0, 4.0, 8.0, 12.0],
            },
        )
        hist.add_record(
            {
                "timestamp": "2026-02-28 18:05:00",
                "sample_name": "sample_b",
                "file_name": "LSV_b",
                "file_path": str(tmp_path / "sample_b.txt"),
                "type": "LSV",
                "status": "success",
                "project_id": "proj_compare",
                "project_name": "Compare Demo",
                "results": {"potential_10": 0.412, "potential_at_10.0": 0.412, "potential_at_50.0": 0.488, "tafel_slope": 92.0},
            },
            data={
                "potential_original": [-0.22, -0.16, -0.1, -0.04],
                "current": [0.8, 3.5, 7.2, 11.5],
            },
        )

        port = _get_free_port()
        manager = V6ServerManager(port=port)
        ok, _ = manager.start()
        assert ok
        try:
            status, payload = _read(
                f"http://127.0.0.1:{port}/api/v1/projects/proj_compare/lsv-compare-plot?sample=sample_a&sample=sample_b"
            )
            assert status == 200
            assert payload.get("status") == "success"
            plot = payload.get("plot") or {}
            assert plot.get("trace_count") == 2
            assert plot.get("selected_samples") == ["sample_a", "sample_b"]
            assert str(plot.get("image_data_url", "")).startswith("data:image/png;base64,")
            assert os.path.exists(plot.get("plot_path"))

            status, payload = _read(
                f"http://127.0.0.1:{port}/api/v1/projects/proj_compare/lsv-target-currents"
            )
            assert status == 200
            assert payload.get("status") == "success"
            assert payload.get("potential_target_currents") == [10.0, 50.0]
            assert payload.get("overpotential_target_currents") == [10.0, 50.0]

            status, payload = _read(
                f"http://127.0.0.1:{port}/api/v1/projects/proj_compare/lsv-compare-plot?sample=sample_a&sample=sample_b&chart_type=bar&metric=potential_at_target&target_current=10"
            )
            assert status == 200
            assert payload.get("status") == "success"
            plot = payload.get("plot") or {}
            assert plot.get("chart_type") == "bar"
            assert plot.get("metric_key") == "potential_at_target"
            assert plot.get("target_current") == pytest.approx(10.0, rel=1e-9)
            assert plot.get("trace_count") == 2
            assert str(plot.get("image_data_url", "")).startswith("data:image/png;base64,")
            assert os.path.exists(plot.get("plot_path"))

            status, payload = _read(
                f"http://127.0.0.1:{port}/api/v1/projects/proj_compare/lsv-compare-plot?sample=sample_a&sample=sample_b&chart_type=bar&metric=potential_at_target&target_current=50"
            )
            assert status == 200
            assert payload.get("status") == "success"
            plot = payload.get("plot") or {}
            assert plot.get("metric_key") == "potential_at_target"
            assert plot.get("target_current") == pytest.approx(50.0, rel=1e-9)
            assert plot.get("metric_label") == "E@50 (V)"
            assert str(plot.get("image_data_url", "")).startswith("data:image/png;base64,")
            assert os.path.exists(plot.get("plot_path"))

            status, payload = _read(
                f"http://127.0.0.1:{port}/api/v1/projects/proj_compare/lsv-compare-plot/latest?chart_type=bar&metric=potential_at_target&target_current=50"
            )
            assert status == 200
            assert payload.get("status") == "success"
            latest_plot = payload.get("plot") or {}
            assert latest_plot.get("chart_type") == "bar"
            assert latest_plot.get("metric_key") == "potential_at_target"
            assert latest_plot.get("target_current") == pytest.approx(50.0, rel=1e-9)
            assert str(latest_plot.get("image_data_url", "")).startswith("data:image/png;base64,")
            assert os.path.exists(latest_plot.get("plot_path"))
        finally:
            manager.stop()
    finally:
        if old_projects is None:
            os.environ.pop("ELECTROCHEM_V6_PROJECTS_FILE", None)
        else:
            os.environ["ELECTROCHEM_V6_PROJECTS_FILE"] = old_projects
        if old_history is None:
            os.environ.pop("ELECTROCHEM_V6_HISTORY_FILE", None)
        else:
            os.environ["ELECTROCHEM_V6_HISTORY_FILE"] = old_history
        if old_conv is None:
            os.environ.pop("ELECTROCHEM_V6_CONVERSATION_FILE", None)
        else:
            os.environ["ELECTROCHEM_V6_CONVERSATION_FILE"] = old_conv


def test_v6_process_route_persists_output_files_to_history(tmp_path, monkeypatch):
    old_projects = os.environ.get("ELECTROCHEM_V6_PROJECTS_FILE")
    old_history = os.environ.get("ELECTROCHEM_V6_HISTORY_FILE")
    old_conv = os.environ.get("ELECTROCHEM_V6_CONVERSATION_FILE")
    reset_runtime()
    try:
        os.environ["ELECTROCHEM_V6_PROJECTS_FILE"] = str(tmp_path / "projects.json")
        os.environ["ELECTROCHEM_V6_HISTORY_FILE"] = str(tmp_path / "history.json")
        os.environ["ELECTROCHEM_V6_CONVERSATION_FILE"] = str(tmp_path / "conversation.json")

        data_dir = tmp_path / "demo_data"
        data_dir.mkdir()
        (data_dir / "LSV-1.txt").write_text("Potential Current\n0 0\n1 0.001\n2 0.002\n", encoding="utf-8")
        output_csv = data_dir / "LSV_results.csv"
        output_csv.write_text("a,b\n1,2\n", encoding="utf-8")
        summary_path = data_dir / "summary.json"

        def _fake_run_modules(folder_path, gui_vars, callbacks=None, resolve_start_line=None):
            run_id = gui_vars.get("run_id")
            hist = get_history_store()
            hist.add_record(
                {
                    "timestamp": "2026-02-28 12:00:00",
                    "sample_name": "sample_a",
                    "file_name": "LSV-1",
                    "file_path": str(data_dir / "LSV-1.txt"),
                    "type": "LSV",
                    "status": "success",
                    "project_id": gui_vars.get("project_id"),
                    "project_name": "demo_project",
                    "run_id": run_id,
                    "results": {"overpotential_10": 0.321},
                }
            )
            return {
                "summary_path": str(summary_path),
                "lsv_csv": str(output_csv),
                "quality_summary": {"passed": 1, "failed": 0},
                "messages": [],
            }

        monkeypatch.setattr(process_service, "_run_selected_modules", _fake_run_modules)
        payload = process_service.process_folder(
            {"folder_path": str(data_dir), "data_type": "LSV", "project_name": "demo_project"}
        )
        assert payload.get("status") == "success"
        hist = get_history_store()
        records = hist.get_all_records()
        assert records
        record = records[-1]
        assert str(output_csv) in (record.get("output_files") or [])
        assert record.get("summary_path") == str(summary_path)
    finally:
        reset_runtime()
        if old_projects is None:
            os.environ.pop("ELECTROCHEM_V6_PROJECTS_FILE", None)
        else:
            os.environ["ELECTROCHEM_V6_PROJECTS_FILE"] = old_projects
        if old_history is None:
            os.environ.pop("ELECTROCHEM_V6_HISTORY_FILE", None)
        else:
            os.environ["ELECTROCHEM_V6_HISTORY_FILE"] = old_history
        if old_conv is None:
            os.environ.pop("ELECTROCHEM_V6_CONVERSATION_FILE", None)
        else:
            os.environ["ELECTROCHEM_V6_CONVERSATION_FILE"] = old_conv


def test_v6_history_manager_serializes_numpy_payload(tmp_path):
    import numpy as np

    old_history = os.environ.get("ELECTROCHEM_V6_HISTORY_FILE")
    reset_runtime()
    try:
        os.environ["ELECTROCHEM_V6_HISTORY_FILE"] = str(tmp_path / "history.json")
        hist = get_history_store()
        hist.add_record(
            {
                "timestamp": "2026-02-28 21:05:00",
                "sample_name": "sample_np",
                "file_name": "LSV-np",
                "file_path": str(tmp_path / "LSV-np.txt"),
                "type": "LSV",
                "status": "success",
                "results": {"value": np.float64(0.123)},
            },
            data={
                "curve": np.array([0.1, 0.2, 0.3]),
                "nested": {"fit": np.array([[1.0, 2.0], [3.0, 4.0]])},
            },
        )
        records = hist.get_all_records()
        assert records
        record = records[-1]
        assert record["results"]["value"] == 0.123
        assert record["data"]["curve"] == [0.1, 0.2, 0.3]
        assert record["data"]["nested"]["fit"] == [[1.0, 2.0], [3.0, 4.0]]
    finally:
        reset_runtime()
        if old_history is None:
            os.environ.pop("ELECTROCHEM_V6_HISTORY_FILE", None)
        else:
            os.environ["ELECTROCHEM_V6_HISTORY_FILE"] = old_history


def test_v6_history_manager_migrates_legacy_list_file(tmp_path):
    old_history = os.environ.get("ELECTROCHEM_V6_HISTORY_FILE")
    reset_runtime()
    try:
        history_path = tmp_path / "history.json"
        history_path.write_text("[]", encoding="utf-8")
        os.environ["ELECTROCHEM_V6_HISTORY_FILE"] = str(history_path)
        hist = get_history_store()
        hist.add_record(
            {
                "timestamp": "2026-02-28 23:10:00",
                "sample_name": "sample_legacy",
                "file_name": "LSV-legacy",
                "file_path": str(tmp_path / "LSV-legacy.txt"),
                "type": "LSV",
                "status": "success",
                "results": {"value": 1.23},
            }
        )
        records = hist.get_all_records()
        assert len(records) >= 1
        found = [r for r in records if r.get("sample_name") == "sample_legacy"]
        assert found
        assert found[0].get("sample_name") == "sample_legacy"
    finally:
        reset_runtime()
        if old_history is None:
            os.environ.pop("ELECTROCHEM_V6_HISTORY_FILE", None)
        else:
            os.environ["ELECTROCHEM_V6_HISTORY_FILE"] = old_history


def test_v6_attach_run_outputs_serializes_quality_summary(tmp_path):
    import numpy as np

    old_history = os.environ.get("ELECTROCHEM_V6_HISTORY_FILE")
    reset_runtime()
    try:
        history_path = tmp_path / "history.json"
        history_path.write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "records": [
                        {
                            "timestamp": "2026-02-28 23:20:00",
                            "sample_name": "sample_qc",
                            "file_name": "LSV-qc",
                            "file_path": str(tmp_path / "LSV-qc.txt"),
                            "type": "LSV",
                            "status": "success",
                            "run_id": "run-qc-1",
                            "results": {},
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        os.environ["ELECTROCHEM_V6_HISTORY_FILE"] = str(history_path)
        get_history_store()
        result = attach_run_outputs(
            run_id="run-qc-1",
            output_files=[str(tmp_path / "summary.json")],
            summary_path=str(tmp_path / "summary.json"),
            quality_summary={"missing_values": np.int64(0), "potential_range": np.array([0.1, 0.2])},
        )
        assert result.get("status") == "success"
        hist = get_history_store()
        records = hist.get_all_records()
        record = [r for r in records if r.get("run_id") == "run-qc-1"][0]
        assert record["quality_summary"]["missing_values"] == 0
        assert record["quality_summary"]["potential_range"] == [0.1, 0.2]
    finally:
        reset_runtime()
        if old_history is None:
            os.environ.pop("ELECTROCHEM_V6_HISTORY_FILE", None)
        else:
            os.environ["ELECTROCHEM_V6_HISTORY_FILE"] = old_history


def test_v6_process_folder_uses_sqlite_history_store(tmp_path, monkeypatch):
    old_projects = os.environ.get("ELECTROCHEM_V6_PROJECTS_FILE")
    old_history = os.environ.get("ELECTROCHEM_V6_HISTORY_FILE")
    old_conv = os.environ.get("ELECTROCHEM_V6_CONVERSATION_FILE")
    reset_runtime()
    try:
        os.environ["ELECTROCHEM_V6_PROJECTS_FILE"] = str(tmp_path / "projects.json")
        os.environ["ELECTROCHEM_V6_HISTORY_FILE"] = str(tmp_path / "history.json")
        os.environ["ELECTROCHEM_V6_CONVERSATION_FILE"] = str(tmp_path / "conversation.json")

        data_dir = tmp_path / "demo_bind_data"
        data_dir.mkdir()
        (data_dir / "LSV-bind.txt").write_text("Potential Current\n0 0\n1 0.001\n2 0.002\n", encoding="utf-8")
        output_csv = data_dir / "LSV_results.csv"
        output_csv.write_text("a,b\n1,2\n", encoding="utf-8")
        summary_path = data_dir / "summary.json"
        summary_path.write_text("{}", encoding="utf-8")

        def _fake_run_modules(folder_path, gui_vars, callbacks=None, resolve_start_line=None):
            hist = get_history_store()
            assert Path(hist.db.path).resolve() == (tmp_path / "electrochem_v6.db").resolve()
            hist.add_record(
                {
                    "timestamp": "2026-02-28 12:30:00",
                    "sample_name": "sample_bind",
                    "file_name": "LSV-bind",
                    "file_path": str(data_dir / "LSV-bind.txt"),
                    "type": "LSV",
                    "status": "success",
                    "project_id": gui_vars.get("project_id"),
                    "project_name": "bind_project",
                    "run_id": gui_vars.get("run_id"),
                    "results": {"overpotential_10": 0.287},
                }
            )
            return {
                "summary_path": str(summary_path),
                "lsv_csv": str(output_csv),
                "quality_summary": {"passed": 1, "failed": 0},
                "messages": [],
            }

        monkeypatch.setattr(process_service, "_run_selected_modules", _fake_run_modules)
        payload = process_service.process_folder(
            {"folder_path": str(data_dir), "data_type": "LSV", "project_name": "bind_project"}
        )
        assert payload.get("status") == "success", payload

        hist = get_history_store()
        records = hist.get_all_records()
        assert len(records) >= 1
        record = [r for r in records if r.get("sample_name") == "sample_bind"][0]
        assert record.get("project_name") == "bind_project"
        assert str(output_csv) in (record.get("output_files") or [])
    finally:
        reset_runtime()
        if old_projects is None:
            os.environ.pop("ELECTROCHEM_V6_PROJECTS_FILE", None)
        else:
            os.environ["ELECTROCHEM_V6_PROJECTS_FILE"] = old_projects
        if old_history is None:
            os.environ.pop("ELECTROCHEM_V6_HISTORY_FILE", None)
        else:
            os.environ["ELECTROCHEM_V6_HISTORY_FILE"] = old_history
        if old_conv is None:
            os.environ.pop("ELECTROCHEM_V6_CONVERSATION_FILE", None)
        else:
            os.environ["ELECTROCHEM_V6_CONVERSATION_FILE"] = old_conv


def test_v6_history_archive_and_delete_routes(tmp_path):
    old_history = os.environ.get("ELECTROCHEM_V6_HISTORY_FILE")
    reset_runtime()
    try:
        history_file = tmp_path / "history.json"
        os.environ["ELECTROCHEM_V6_HISTORY_FILE"] = str(history_file)
        history_file.write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "records": [
                        {
                            "timestamp": "2026-02-28 10:00:00",
                            "sample_name": "sample_a",
                            "file_name": "LSV-1",
                            "file_path": str(tmp_path / "LSV-1.txt"),
                            "type": "LSV",
                            "status": "success",
                            "project_id": "p1",
                        },
                        {
                            "timestamp": "2026-02-28 11:00:00",
                            "sample_name": "sample_b",
                            "file_name": "CV-1",
                            "file_path": str(tmp_path / "CV-1.txt"),
                            "type": "CV",
                            "status": "success",
                            "project_id": "p1",
                        },
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        port = _get_free_port()
        manager = V6ServerManager(port=port)
        ok, _ = manager.start()
        assert ok
        try:
            archive_key = f"2026-02-28 10:00:00|LSV|{tmp_path / 'LSV-1.txt'}"
            status, payload = _read(
                f"http://127.0.0.1:{port}/api/v1/history/archive",
                method="POST",
                payload={"history_key": archive_key},
            )
            assert status == 200
            assert payload.get("status") == "success"

            status, payload = _read(f"http://127.0.0.1:{port}/api/v1/history?project=p1&limit=10")
            assert status == 200
            names = [item.get("sample_name") for item in payload.get("records") or []]
            assert "sample_a" not in names
            assert "sample_b" in names

            status, payload = _read(f"http://127.0.0.1:{port}/api/v1/stats?project=p1")
            assert status == 200
            assert payload.get("data", {}).get("total_files") == 1

            delete_key = f"2026-02-28 11:00:00|CV|{tmp_path / 'CV-1.txt'}"
            status, payload = _read(
                f"http://127.0.0.1:{port}/api/v1/history/delete",
                method="POST",
                payload={"history_key": delete_key},
            )
            assert status == 200
            assert payload.get("status") == "success"
            assert payload.get("artifact_cleanup") == {
                "removed": [],
                "skipped": [],
                "bytes_reclaimed": 0,
            }

            status, payload = _read(f"http://127.0.0.1:{port}/api/v1/history?project=p1&limit=10&include_archived=1")
            assert status == 200
            items = payload.get("records") or []
            assert len(items) == 1
            assert items[0].get("sample_name") == "sample_a"
            assert items[0].get("archived") is True
        finally:
            manager.stop()
    finally:
        reset_runtime()
        if old_history is None:
            os.environ.pop("ELECTROCHEM_V6_HISTORY_FILE", None)
        else:
            os.environ["ELECTROCHEM_V6_HISTORY_FILE"] = old_history


def test_v6_project_report_route(monkeypatch):
    port = _get_free_port()
    manager = V6ServerManager(port=port)
    ok, _ = manager.start()
    assert ok
    try:
        name = f"v6_report_{uuid.uuid4().hex[:8]}"
        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/projects",
            method="POST",
            payload={"name": name, "description": "report test"},
        )
        assert status == 200
        project_id = payload.get("project_id")
        assert project_id

        monkeypatch.setattr(
            routes_get,
            "export_project_report",
            lambda project, report_data, output_dir: {
                "status": "success",
                "path": os.path.join(output_dir, "mock_report.md"),
                "file_name": "mock_report.md",
            },
        )
        status, payload = _read(f"http://127.0.0.1:{port}/api/v1/projects/{project_id}/report")
        assert status == 200
        assert payload.get("status") == "success"
        assert payload.get("file_name") == "mock_report.md"
    finally:
        manager.stop()


def test_v6_process_templates_routes(monkeypatch):
    port = _get_free_port()
    manager = V6ServerManager(port=port)
    ok, _ = manager.start()
    assert ok
    try:
        def _fake_list_templates():
            return {
                "status": "success",
                "templates": [{"name": "LSV_常用模板", "builtin": True, "state": {"selected_types": ["LSV"]}}],
            }

        def _fake_save_template(name, state, overwrite=False):
            return {"status": "success", "template": {"name": name, "state": state, "overwrite": overwrite}}

        def _fake_delete_template(name):
            return {"status": "success", "name": name}

        monkeypatch.setattr(routes_get, "list_process_templates", _fake_list_templates)
        monkeypatch.setattr(routes_post, "save_process_template", _fake_save_template)
        monkeypatch.setattr(routes_post, "delete_process_template", _fake_delete_template)

        status, payload = _read(f"http://127.0.0.1:{port}/api/v1/process/templates")
        assert status == 200
        assert payload.get("status") == "success"
        assert isinstance(payload.get("templates"), list)

        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/process/templates",
            method="POST",
            payload={"name": "MyTemplate", "state": {"selected_types": ["LSV"]}},
        )
        assert status == 200
        assert payload.get("status") == "success"
        assert payload.get("template", {}).get("name") == "MyTemplate"

        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/process/templates/MyTemplate/delete",
            method="POST",
            payload={},
        )
        assert status == 200
        assert payload.get("status") == "success"
        assert payload.get("name") == "MyTemplate"
    finally:
        manager.stop()


def test_v6_process_templates_roundtrip_real(tmp_path):
    from electrochem_v6.core.processing_registry import PARAM_SCHEMA_VERSION

    port = _get_free_port()
    manager = V6ServerManager(port=port)
    old_file = os.environ.get("ELECTROCHEM_V6_TEMPLATE_FILE")
    os.environ["ELECTROCHEM_V6_TEMPLATE_FILE"] = str(tmp_path / "templates_test.json")
    ok, _ = manager.start()
    assert ok
    try:
        status, payload = _read(f"http://127.0.0.1:{port}/api/v1/process/templates")
        assert status == 200
        assert payload.get("status") == "success"

        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/process/templates/",
            method="POST",
            payload={"name": "roundtrip_tmp", "state": {"selected_types": ["LSV"]}},
        )
        assert status == 200
        assert payload.get("status") == "success"
        assert payload.get("template", {}).get("state", {}).get("schema_version") == PARAM_SCHEMA_VERSION
        assert not (tmp_path / "templates_test.json").exists()

        status, payload = _read(f"http://127.0.0.1:{port}/api/v1/process/templates")
        assert status == 200
        names = [item.get("name") for item in payload.get("templates", [])]
        assert "roundtrip_tmp" in names
        roundtrip = next(item for item in payload["templates"] if item.get("name") == "roundtrip_tmp")
        assert roundtrip["state"]["schema_version"] == PARAM_SCHEMA_VERSION

        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/process/templates/roundtrip_tmp/delete/",
            method="POST",
            payload={},
        )
        assert status == 200
        assert payload.get("status") == "success"
    finally:
        if old_file is None:
            os.environ.pop("ELECTROCHEM_V6_TEMPLATE_FILE", None)
        else:
            os.environ["ELECTROCHEM_V6_TEMPLATE_FILE"] = old_file
        manager.stop()


def test_v6_llm_test_connection_endpoint(monkeypatch):
    port = _get_free_port()
    manager = V6ServerManager(port=port)
    ok, _ = manager.start()
    assert ok
    try:
        def _fake_check_provider_connection(payload):
            return {
                "status": "success",
                "provider": payload.get("provider"),
                "model": payload.get("model"),
                "message": "连接测试通过",
            }

        monkeypatch.setattr(routes_post, "check_provider_connection", _fake_check_provider_connection)
        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/llm/test",
            method="POST",
            payload={"provider": "openai", "model": "gpt-test"},
        )
        assert status == 200
        assert payload.get("status") == "success"
        assert payload.get("provider") == "openai"
    finally:
        manager.stop()


class _DummyAgentService:
    def chat(
        self,
        *,
        message,
        conversation_id=None,
        provider=None,
        model=None,
        project_name=None,
        data_type=None,
        processing_result=None,
        attachments=None,
        prompt_prefix=None,
        professional_context=None,
        approval_id=None,
        approval_action=None,
        progress_callback=None,
        cancel_check=None,
    ):
        if progress_callback:
            progress_callback("stub thinking")
        assert cancel_check is None or cancel_check() is False
        cid = conversation_id or f"v6_conv_{uuid.uuid4().hex[:8]}"
        meta = {
            "provider": provider or "mock",
            "model": model or "mock-model",
            "project_name": project_name,
            "data_type": data_type,
        }
        cid = append_message(cid, "user", message, metadata=meta)
        append_message(cid, "agent", "stub reply", metadata=meta)
        conv = get_conversation(cid)
        return {
            "status": "success",
            "conversation_id": cid,
            "provider": meta["provider"],
            "model": meta["model"],
            "agent_reply": "stub reply",
            "processing_result": processing_result,
            "attachments": attachments or [],
            "messages": conv.get("messages", []) if conv else [],
            "conversation": conv,
        }

    def delete_session(self, conversation_id):
        return None


def test_v6_agent_message_and_delete():
    port = _get_free_port()
    manager = V6ServerManager(port=port)
    manager._agent_service = _DummyAgentService()
    ok, _ = manager.start()
    assert ok
    try:
        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/agent/messages",
            method="POST",
            payload={"message": "hello"},
        )
        assert status == 200
        assert payload.get("status") == "success"
        cid = payload.get("conversation_id")
        assert cid

        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/agent/conversations/{cid}/delete",
            method="POST",
            payload={},
        )
        assert status == 200
        assert payload.get("status") == "success"
    finally:
        manager.stop()


def test_v6_background_agent_job_routes():
    port = _get_free_port()
    manager = V6ServerManager(port=port)
    manager._agent_service = _DummyAgentService()
    ok, _ = manager.start()
    assert ok
    try:
        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/agent/jobs",
            method="POST",
            payload={"message": "hello background"},
        )
        assert status == 202
        job_id = payload.get("job_id")
        assert job_id

        job = None
        for _ in range(100):
            status, detail = _read(f"http://127.0.0.1:{port}/api/v1/agent/jobs/{job_id}")
            assert status == 200
            job = detail.get("job")
            if job and job.get("status") in {"failed", "succeeded", "cancelled"}:
                break
            time.sleep(0.02)
        assert job and job.get("status") == "succeeded"
        assert job.get("kind") == "agent"
        assert job.get("result", {}).get("agent_reply") == "stub reply"
    finally:
        manager.stop()


def test_v6_agent_conversation_rename():
    port = _get_free_port()
    manager = V6ServerManager(port=port)
    manager._agent_service = _DummyAgentService()
    ok, _ = manager.start()
    assert ok
    try:
        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/agent/messages",
            method="POST",
            payload={"message": "hello rename"},
        )
        assert status == 200
        assert payload.get("status") == "success"
        cid = payload.get("conversation_id")
        assert cid

        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/agent/conversations/{cid}/rename",
            method="POST",
            payload={"title": "重命名会话A"},
        )
        assert status == 200
        assert payload.get("status") == "success"
        assert payload.get("title") == "重命名会话A"

        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/agent/conversations/{cid}",
            method="GET",
        )
        assert status == 200
        assert payload.get("status") == "success"
        assert payload.get("conversation", {}).get("title") == "重命名会话A"
    finally:
        manager.stop()


def test_v6_agent_conversation_list_keyword_filter():
    port = _get_free_port()
    manager = V6ServerManager(port=port)
    manager._agent_service = _DummyAgentService()
    ok, _ = manager.start()
    assert ok
    try:
        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/agent/messages",
            method="POST",
            payload={"message": "hello alpha", "project_name": "alpha_project"},
        )
        assert status == 200
        assert payload.get("status") == "success"

        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/agent/messages",
            method="POST",
            payload={"message": "hello beta", "project_name": "beta_project"},
        )
        assert status == 200
        assert payload.get("status") == "success"

        status, payload = _read(
            f"http://127.0.0.1:{port}/api/v1/agent/conversations?page=1&page_size=20&keyword=alpha_project"
        )
        assert status == 200
        assert payload.get("status") == "success"
        items = payload.get("items") or []
        assert items
        assert all("alpha_project" in str((it.get("project_name") or "")) for it in items)
    finally:
        manager.stop()


def test_v6_agent_message_multipart_without_file():
    port = _get_free_port()
    manager = V6ServerManager(port=port)
    manager._agent_service = _DummyAgentService()
    ok, _ = manager.start()
    assert ok
    try:
        body, headers = _build_multipart({"message": "hello multipart", "provider": "mock"}, [])
        status, payload = _read_raw(
            f"http://127.0.0.1:{port}/api/v1/agent/messages",
            method="POST",
            data=body,
            headers=headers,
        )
        assert status == 200
        assert payload.get("status") == "success"
        assert payload.get("agent_reply") == "stub reply"
    finally:
        manager.stop()


def test_v6_agent_message_multipart_with_zip(monkeypatch):
    port = _get_free_port()
    manager = V6ServerManager(port=port)
    manager._agent_service = _DummyAgentService()
    ok, _ = manager.start()
    assert ok
    try:
        def _fake_process_folder(_payload):
            return {
                "status": "success",
                "result": {
                    "summary": "mock process ok",
                    "processing": {"output_files": ["summary.json"]},
                    "quality_summary": {"total_files": 1},
                },
            }

        monkeypatch.setattr(routes_post, "process_folder", _fake_process_folder)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("demo/LSV_1.txt", "Potential Current\n0 0\n")
        zip_bytes = buf.getvalue()

        body, headers = _build_multipart(
            {"message": "请总结", "data_type": "LSV", "project_name": "mp_test"},
            [("file", "demo.zip", zip_bytes, "application/zip")],
        )
        status, payload = _read_raw(
            f"http://127.0.0.1:{port}/api/v1/agent/messages",
            method="POST",
            data=body,
            headers=headers,
        )
        assert status == 200
        assert payload.get("status") == "success"
        assert payload.get("processing_result", {}).get("summary") == "mock process ok"
        assert isinstance(payload.get("attachments"), list)
        assert payload.get("attachments")
    finally:
        manager.stop()


def test_v6_background_agent_job_multipart_with_zip(monkeypatch, tmp_path):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "agent-job-runtime"))
    reset_runtime()
    port = _get_free_port()
    manager = V6ServerManager(port=port)
    manager._agent_service = _DummyAgentService()
    ok, _ = manager.start()
    assert ok
    try:
        def _fake_process_folder(payload):
            assert payload.get("_cancel_check") is not None
            payload["_progress_callback"](1, 1, "LSV_1.txt")
            return {
                "status": "success",
                "result": {
                    "summary": "queued process ok",
                    "processing": {"output_files": ["summary.json"]},
                    "quality_summary": {"total_files": 1},
                },
            }

        monkeypatch.setattr(routes_post, "process_folder", _fake_process_folder)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("demo/LSV_1.txt", "Potential Current\n0 0\n")
        body, headers = _build_multipart(
            {"message": "summarize", "data_type": "LSV", "project_name": "job_upload"},
            [("file", "demo.zip", buf.getvalue(), "application/zip")],
        )
        status, payload = _read_raw(
            f"http://127.0.0.1:{port}/api/v1/agent/jobs",
            method="POST",
            data=body,
            headers=headers,
        )
        assert status == 202
        job_id = payload["job_id"]

        job = None
        for _ in range(100):
            status, detail = _read(f"http://127.0.0.1:{port}/api/v1/agent/jobs/{job_id}")
            assert status == 200
            job = detail.get("job")
            if job and job.get("status") in {"failed", "succeeded", "cancelled"}:
                break
            time.sleep(0.02)
        assert job and job.get("status") == "succeeded"
        result = job.get("result", {})
        assert result.get("processing_result", {}).get("summary") == "queued process ok"
        source_path = result["processing_result"]["provenance"]["source_archive_path"]
        assert os.path.exists(source_path)
        assert result.get("attachments")
    finally:
        manager.stop()
        reset_runtime()


# ---------- _parse_params_value dict input ----------


def test_v6_parse_params_value_accepts_dict():
    """_parse_params_value should return dict input as-is without JSON round-trip."""
    from electrochem_v6.server.routes_post import _parse_params_value

    d = {"font_size": 14, "nested": {"a": 1}}
    assert _parse_params_value(d) is d  # exact same object, no copy


def test_v6_parse_params_value_accepts_json_string():
    from electrochem_v6.server.routes_post import _parse_params_value

    assert _parse_params_value('{"k": 1}') == {"k": 1}


def test_v6_parse_params_value_rejects_non_object():
    from electrochem_v6.server.routes_post import _parse_params_value

    with pytest.raises(ValueError, match="JSON 对象"):
        _parse_params_value("[1,2]")


def test_v6_parse_params_value_returns_none_for_falsy():
    from electrochem_v6.server.routes_post import _parse_params_value

    assert _parse_params_value(None) is None
    assert _parse_params_value("") is None


# ---------- HTTP limits env var override ----------


def test_v6_http_limits_configurable_via_env(monkeypatch):
    """Handler class attributes should reflect env var overrides."""
    monkeypatch.setenv("ELECTROCHEM_V6_MAX_JSON_BYTES", "1024")
    monkeypatch.setenv("ELECTROCHEM_V6_MAX_ZIP_FILES", "99")

    # Force re-creation of the handler class with new env values
    port = _get_free_port()
    mgr = V6ServerManager(port=port)
    ok, _ = mgr.start()
    assert ok
    try:
        handler_cls = mgr._server.RequestHandlerClass
        assert handler_cls.MAX_JSON_BODY_BYTES == 1024
        assert handler_cls.MAX_ZIP_FILES == 99
    finally:
        mgr.stop()
