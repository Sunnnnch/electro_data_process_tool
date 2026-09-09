"""Official MCP ClientSession subprocess tests against a real scientific HTTP API."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import socket
import sys
import time
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from electrochem_v6.core import system_service
from electrochem_v6.desktop.mcp_integration import DesktopServiceDiscovery
from electrochem_v6.server.http_server import V6ServerManager
from electrochem_v6.store.runtime import reset_runtime

ROOT = Path(__file__).resolve().parents[1]
READ_TOOLS = {"list_projects", "search_results", "get_result", "get_run", "get_processing_schema", "list_templates",
              "preflight_process", "list_jobs", "get_job", "compare_results"}
WRITE_TOOLS = {"start_process", "export_report"}


@pytest.fixture
def mcp_api(tmp_path, monkeypatch):
    data_dir = tmp_path / "runtime"
    # macOS pytest temp directories are outside the home/workspace roots.
    # Model explicit file selection for this synthetic root only, and restore
    # the previous allow-list when the fixture finishes.
    monkeypatch.setattr(system_service, "_runtime_allowed_dirs", set())
    system_service.register_allowed_dir(str(tmp_path))
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(data_dir))
    for key in ("PROJECTS", "HISTORY", "CONVERSATION", "TEMPLATE", "QUALITY_REPORT", "LOG", "LLM_CONFIG"):
        monkeypatch.delenv(f"ELECTROCHEM_V6_{key}_FILE", raising=False)
    reset_runtime()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    manager = V6ServerManager(port=port)
    assert manager.start()[0]
    discovery = DesktopServiceDiscovery(data_dir, port, manager.session_token)
    discovery.publish()
    try:
        yield manager, data_dir
    finally:
        runner = manager._job_manager
        discovery.close()
        manager.stop()
        if runner:
            runner._executor.shutdown(wait=True)
        reset_runtime()


def child_parameters(data_dir, *, allow_write=False):
    code = "import sys; from electrochem_v6.mcp.server import run_server; run_server(data_dir=sys.argv[1],allow_write=sys.argv[2]=='1')"
    environment = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8"}
    return StdioServerParameters(command=sys.executable, args=["-c", code, str(data_dir), "1" if allow_write else "0"],
                                 cwd=ROOT, env=environment)


def output(result):
    assert not result.isError, result
    value = result.structuredContent
    assert isinstance(value, dict)
    return value


def test_read_only_stdio_handshake_tools_validation_and_unavailable_service(mcp_api, tmp_path):
    manager, data_dir = mcp_api
    stderr_path = tmp_path / "mcp-stderr.log"

    async def exercise():
        with stderr_path.open("w", encoding="utf-8") as stderr:
            async with stdio_client(child_parameters(data_dir), errlog=stderr) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    initialized = await session.initialize()
                    assert initialized.serverInfo.name == "ElectroChem"
                    listed = await session.list_tools()
                    assert {tool.name for tool in listed.tools} == READ_TOOLS
                    assert all(tool.annotations and tool.annotations.readOnlyHint and tool.annotations.idempotentHint
                               and not tool.annotations.destructiveHint and not tool.annotations.openWorldHint for tool in listed.tools)
                    assert output(await session.call_tool("list_projects"))["status"] == "success"
                    assert output(await session.call_tool("list_templates"))["templates"]
                    schema = output(await session.call_tool("get_processing_schema", {"data_types": ["LSV", "CV"]}))["schema"]
                    assert set(schema["data_types"]) == {"LSV", "CV"}
                    assert {"cv_scan_rate_v_s", "tafel_range"} <= {item["key"] for item in schema["parameters"]}
                    for name, arguments in [
                        ("start_process", {}), ("export_report", {}),
                        ("list_projects", {"limit": 0}), ("list_projects", {"limit": "10"}),
                        ("list_projects", {"arbitrary_url": "http://example.invalid"}),
                        ("get_result", {"record_key": "missing-record"}),
                    ]:
                        assert (await session.call_tool(name, arguments)).isError
                    manager.close_desktop_admission()
                    assert output(await session.call_tool("list_jobs"))["status"] == "success"
                    manager.stop()
                    unavailable = await session.call_tool("list_projects")
                    assert unavailable.isError
                    assert isinstance(unavailable.structuredContent, dict)
                    assert unavailable.structuredContent["code"] == "service_unavailable"
                    assert manager.session_token not in str(unavailable)

    asyncio.run(exercise())
    logs = stderr_path.read_text(encoding="utf-8")
    assert "Failed to parse" not in logs and "成功设置中文字体" not in logs


def test_write_stdio_real_cv_exact_selection_new_outputs_compare_and_report(mcp_api, tmp_path):
    manager, data_dir = mcp_api
    source = tmp_path / "CV_selected.txt"
    rows = []
    for _ in range(2):
        rows.extend((k / 60, 0.001 * (k / 60)) for k in range(61))
        rows.extend((k / 60, -0.001 * (k / 60)) for k in range(59, -1, -1))
    original = "\n".join(f"{v:.9f}\t{i:.9f}" for v, i in rows).encode()
    source.write_bytes(original)
    (tmp_path / "CV_unselected.txt").write_bytes(original)
    request = {"data_types": ["CV"], "folder_path": str(tmp_path), "project_name": "MCP exact CV",
               "input_files": [{"data_type": "CV", "path": str(source)}],
               "params": {"cv_potential_column": 1, "cv_current_column": 2, "cv_potential_unit": "V", "cv_current_unit": "A", "cv_scan_rate_v_s": 0.05}}
    empty_folder = tmp_path / "empty-inputs"
    empty_folder.mkdir()
    stderr_path = tmp_path / "mcp-write-stderr.log"

    async def exercise():
        with stderr_path.open("w", encoding="utf-8") as stderr:
            async with stdio_client(child_parameters(data_dir, allow_write=True), errlog=stderr) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    tools = (await session.list_tools()).tools
                    assert {tool.name for tool in tools} == READ_TOOLS | WRITE_TOOLS
                    for tool in tools:
                        if tool.name in WRITE_TOOLS:
                            assert tool.annotations and not tool.annotations.readOnlyHint and not tool.annotations.idempotentHint
                            assert not tool.annotations.destructiveHint and not tool.annotations.openWorldHint
                    initial = output(await session.call_tool("list_jobs"))["total"]
                    for changes in [
                        {"output_dir": str(tmp_path)}, {"params": {"output_run_dir_enabled": False}},
                        {"params": {"_recipe_run_context": {}}}, {"params": {"unknown_parameter": 1}},
                        {"params": {"coupled_results_csv_filename": "../escape.csv"}},
                        {"input_files": [{"path": str(tmp_path / "missing.txt"), "data_type": "CV"}]},
                    ]:
                        rejected = await session.call_tool("start_process", {"request": {**request, **changes}})
                        assert rejected.isError, changes
                    assert output(await session.call_tool("list_jobs"))["total"] == initial
                    unrunnable = await session.call_tool("start_process", {"request": {**request, "folder_path": str(empty_folder), "input_files": None}})
                    assert unrunnable.isError and isinstance(unrunnable.structuredContent, dict)
                    assert unrunnable.structuredContent["code"] == "preflight_failed"
                    assert output(await session.call_tool("list_jobs"))["total"] == initial
                    checked = output(await session.call_tool("preflight_process", {"request": request}))
                    assert checked["preflight"]["runnable"] is True
                    assert checked["preflight"]["selected_matched"] == 1
                    runs, records, old_files = [], [], {}
                    for _ in range(2):
                        submitted = output(await session.call_tool("start_process", {"request": request}))
                        deadline = time.monotonic() + 30
                        while time.monotonic() < deadline:
                            job = output(await session.call_tool("get_job", {"job_id": submitted["job_id"]}))["task"]
                            if job["status"] not in {"queued", "running"}:
                                break
                            await asyncio.sleep(0.05)
                        assert job["status"] == "succeeded", job
                        reference = job["reference"]
                        assert len(reference["record_keys"]) == 1
                        run = output(await session.call_tool("get_run", {"run_id": reference["run_id"]}))["run"]
                        record = output(await session.call_tool("get_result", {"record_key": reference["record_keys"][0]}))["record"]
                        assert run["params"]["cv_scan_rate_v_s"] == 0.05
                        assert Path(run["output_dir"]).parent == tmp_path / "electrochem_outputs"
                        assert record["file_path"] == str(source)
                        assert any(item["sha256"] == hashlib.sha256(original).hexdigest() for item in run["inputs"])
                        runs.append(run)
                        records.append(record)
                        if not old_files:
                            old_files = {path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
                                         for path in record["output_files"] if Path(path).is_file()}
                    assert runs[0]["run_id"] != runs[1]["run_id"]
                    assert runs[0]["output_dir"] != runs[1]["output_dir"]
                    assert source.read_bytes() == original
                    assert old_files and all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == value for path, value in old_files.items())
                    history = output(await session.call_tool("search_results", {"project_id": runs[0]["project_id"], "data_type": "CV"}))
                    assert len(history["records"]) == 2
                    comparison = output(await session.call_tool("compare_results", {"left_record_key": records[0]["record_key"],
                                        "right_record_key": records[1]["record_key"], "project_id": runs[0]["project_id"]}))
                    assert comparison["comparison"]["sources"]["state"] == "unchanged"
                    report = output(await session.call_tool("export_report", {"project_id": runs[0]["project_id"], "run_ids": [runs[0]["run_id"]]}))
                    assert report["scope"]["record_count"] == 1
                    assert Path(report["path"]).is_file()
                    text = Path(report["path"]).read_text(encoding="utf-8")
                    assert runs[0]["run_id"] in text and runs[1]["run_id"] not in text
                    assert (await session.call_tool("export_report", {"project_id": runs[0]["project_id"]})).isError
                    assert manager.session_token not in json.dumps(report)

    asyncio.run(exercise())
    assert "Failed to parse" not in stderr_path.read_text(encoding="utf-8")
