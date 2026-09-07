"""Exercise real processing, historical replay, exact comparison, and reports over HTTP."""

from __future__ import annotations

import hashlib
import json
import math
import socket
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from electrochem_v6.server import V6ServerManager
from electrochem_v6.store.runtime import reset_runtime


def request_json(base, path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(base + path, data=data, headers={"Content-Type": "application/json"})
    try:
        response = urlopen(request, timeout=30)
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.loads(response.read())


@pytest.fixture
def workflow_server(tmp_path, monkeypatch):
    isolated = tmp_path / "runtime"
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(isolated))
    for key in ("PROJECTS", "HISTORY", "CONVERSATION", "TEMPLATE", "QUALITY_REPORT", "LOG", "LLM_CONFIG"):
        monkeypatch.delenv(f"ELECTROCHEM_V6_{key}_FILE", raising=False)
    reset_runtime()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    manager = V6ServerManager(port=port)
    ok, message = manager.start()
    assert ok, message
    try:
        yield f"http://127.0.0.1:{port}", isolated
    finally:
        manager.stop()
        reset_runtime()


def wait_job(base, job_id):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        status, payload = request_json(base, f"/api/v1/process/jobs/{job_id}")
        assert status == 200, payload
        job = payload["job"]
        if job["status"] in {"succeeded", "failed", "cancelled"}:
            assert job["status"] == "succeeded", job
            return job
        time.sleep(0.05)
    pytest.fail("historical replay did not finish")


def test_processing_replay_compare_and_scoped_report_preserve_original_outputs(workflow_server, tmp_path):
    base, _isolated = workflow_server
    source = tmp_path / "LSV_sample.txt"
    original_text = "\n".join(f"{0.20 + 0.06 * math.log10(j):.9f}\t{j / 1000:.9f}" for j in range(1, 31))
    source.write_text(original_text, encoding="utf-8")
    status, project = request_json(base, "/api/v1/projects", {"name": "复算集成测试"})
    assert status == 200, project
    project_id = project["project"]["id"]
    status, processed = request_json(base, "/api/v1/process", {
        "project_id": project_id, "folder_path": str(tmp_path), "data_types": ["LSV"],
        "input_files": [{"path": str(source), "data_type": "LSV"}],
        "params": {"area": 1, "potential_offset": 0, "tafel_enabled": True,
                   "tafel_range": "1-10", "lsv_target_current": "10", "lsv_export_data": True,
                   "overpotential_enabled": True, "eq_potential": 0},
    })
    assert status == 200, processed
    first_result = processed["result"]
    old_run_id = first_result["manifest"]["run"]["run_id"]
    assert {"lsv.current_density", "lsv.manual_potential_offset", "lsv.target_potential", "lsv.tafel_fit"} <= {
        item["key"] for item in first_result["manifest"]["calculation"]["formulas"]
    }
    old_outputs = {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in map(Path, first_result["processing"]["output_files"]) if path.is_file()
    }
    status, history = request_json(base, "/api/v1/history?" + urlencode({"project_id": project_id, "limit": 50}))
    assert status == 200
    old_record = next(record for record in history["records"] if record["run_id"] == old_run_id)
    selection = {"record_key": old_record["record_key"], "params": {"potential_offset": 0.05}}
    status, plan = request_json(base, f"/api/v1/runs/{old_run_id}/replay-plan", selection)
    assert status == 200, plan
    assert plan["plan"]["can_replay"], plan
    assert all(check["state"] == "unchanged" for check in plan["plan"]["source_checks"])
    assert any(change["key"] == "potential_offset" for change in plan["plan"]["parameter_changes"])
    status, submitted = request_json(base, f"/api/v1/runs/{old_run_id}/replay", selection)
    assert status == 202, submitted
    wait_job(base, submitted["job_id"])
    status, history = request_json(base, "/api/v1/history?" + urlencode({"project_id": project_id, "limit": 50}))
    assert status == 200
    assert len(history["records"]) == 2, history
    new_record = next(record for record in history["records"] if record["run_id"] != old_run_id)
    new_run_id = new_record["run_id"]
    status, stored = request_json(base, f"/api/v1/runs/{new_run_id}")
    assert status == 200, stored
    assert stored["run"]["parent_run_id"] == old_run_id
    assert stored["run"]["parent_record_key"] == old_record["record_key"]
    assert stored["run"]["output_dir"] != first_result["processing"]["output_dir"]
    for path, digest in old_outputs.items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
    status, compared = request_json(base, "/api/v1/history/compare", {
        "left_record_key": old_record["record_key"], "right_record_key": new_record["record_key"], "project_id": project_id,
    })
    assert status == 200, compared
    metrics = {item["key"]: item for item in compared["comparison"]["metrics"]}
    assert metrics["potential_at_10"]["delta"] == pytest.approx(0.05)
    assert metrics["tafel_slope"]["delta"] == pytest.approx(0, abs=1e-8)
    assert compared["comparison"]["sources"]["state"] == "unchanged"

    status, report = request_json(base, f"/api/v1/projects/{project_id}/report", {"run_ids": [old_run_id]})
    assert status == 200, report
    assert report["scope"]["record_count"] == 1
    assert Path(report["path"]).is_file()
    assert Path(report["html_path"]).is_file()
    text = Path(report["path"]).read_text(encoding="utf-8")
    assert old_run_id in text
    assert new_run_id not in text
    assert "potential_offset" in text
    assert "TafelSlope = 1000*b" in text
    assert hashlib.sha256(source.read_bytes()).hexdigest() in text

    # A changed source must require an explicit choice before submitting any job.
    source.write_text(original_text + "\n0.300000000\t0.031000000", encoding="utf-8")
    status, changed = request_json(base, f"/api/v1/runs/{old_run_id}/replay-plan", {})
    assert status == 200, changed
    assert changed["plan"]["requires_changed_confirmation"]
    assert not changed["plan"]["can_replay"]
    status, blocked = request_json(base, f"/api/v1/runs/{old_run_id}/replay", {})
    assert status == 409, blocked
    assert "job_id" not in blocked
    status, acknowledged = request_json(base, f"/api/v1/runs/{old_run_id}/replay-plan", {"allow_changed_sources": True})
    assert status == 200 and acknowledged["plan"]["can_replay"], acknowledged
