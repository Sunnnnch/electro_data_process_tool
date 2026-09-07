import io
import json
import zipfile

import pytest

from electrochem_v6.core.project_archive import (
    ProjectArchiveLimitError,
    build_project_archive,
    write_project_archive,
)
from electrochem_v6.server import routes_get


def test_project_archive_preserves_runs_and_includes_trusted_output_roots(tmp_path):
    run_a = tmp_path / "data_a"
    run_b = tmp_path / "data_b"
    app_output = tmp_path / "runtime" / "project_reports"
    outside = tmp_path / "outside"
    for directory in (run_a, run_b, app_output, outside):
        directory.mkdir(parents=True)

    source_a = run_a / "input.txt"
    source_b = run_b / "input.txt"
    result_a = run_a / "result.csv"
    result_b = run_b / "result.csv"
    duplicate_a = app_output / "result.csv"
    summary_a = app_output / "summary.json"
    uploaded_source = app_output / "original_upload.zip"
    forbidden = outside / "secret.txt"
    for path, content in (
        (source_a, "source-a"),
        (source_b, "source-b"),
        (result_a, "result-a"),
        (result_b, "result-b"),
        (duplicate_a, "result-a-external"),
        (summary_a, "summary-a"),
        (uploaded_source, "zip-source"),
        (forbidden, "not-exported"),
    ):
        path.write_text(content, encoding="utf-8")

    result = build_project_archive(
        [
            {
                "run_id": "run-a",
                "folder_path": str(run_a),
                "file_path": str(source_a),
                "output_files": [str(result_a), str(duplicate_a), str(forbidden)],
                "summary_path": str(summary_a),
                "source_archive_path": str(uploaded_source),
            },
            {
                "run_id": "run-b",
                "folder_path": str(run_b),
                "file_path": str(source_b),
                "output_files": [str(result_b)],
            },
        ],
        application_roots=[app_output],
    )

    with zipfile.ZipFile(io.BytesIO(result.data)) as archive:
        names = archive.namelist()
        assert archive.read("runs/0001_run-a/results/result.csv") == b"result-a"
        assert archive.read("runs/0001_run-a/results/result_2.csv") == b"result-a-external"
        assert archive.read("runs/0001_run-a/results/summary.json") == b"summary-a"
        assert archive.read("runs/0001_run-a/source/input.txt") == b"source-a"
        assert archive.read("runs/0001_run-a/source/original_upload.zip") == b"zip-source"
        assert archive.read("runs/0002_run-b/results/result.csv") == b"result-b"
        assert archive.read("runs/0002_run-b/source/input.txt") == b"source-b"
        manifest = json.loads(archive.read("archive_manifest.json"))

    assert result.file_count == 7
    assert result.total_uncompressed_bytes == sum(
        path.stat().st_size
        for path in (source_a, source_b, result_a, result_b, duplicate_a, summary_a, uploaded_source)
    )
    assert manifest["file_count"] == 7
    assert str(forbidden.resolve()) in result.skipped_files
    assert manifest["skipped_files"] == [str(forbidden.resolve())]
    assert all("secret.txt" not in name for name in names)


def test_project_archive_deduplicates_outputs_attached_to_multiple_records(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    output = data_dir / "result.csv"
    output.write_text("result", encoding="utf-8")

    result = build_project_archive(
        [
            {"run_id": "shared", "folder_path": str(data_dir), "output_files": [str(output)]},
            {"run_id": "shared", "folder_path": str(data_dir), "output_files": [str(output)]},
        ],
        application_roots=[],
    )

    with zipfile.ZipFile(io.BytesIO(result.data)) as archive:
        assert archive.namelist() == [
            "runs/0001_shared/results/result.csv",
            "archive_manifest.json",
        ]
    assert result.file_count == 1


def test_project_archive_enforces_file_and_uncompressed_byte_limits(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    first = data_dir / "first.txt"
    second = data_dir / "second.txt"
    first.write_text("1234", encoding="utf-8")
    second.write_text("5678", encoding="utf-8")
    records = [
        {
            "run_id": "limited",
            "folder_path": str(data_dir),
            "output_files": [str(first), str(second)],
        }
    ]

    with pytest.raises(ProjectArchiveLimitError, match="文件数"):
        build_project_archive(records, application_roots=[], max_files=1)
    with pytest.raises(ProjectArchiveLimitError, match="体积"):
        build_project_archive(records, application_roots=[], max_uncompressed_bytes=7)


def test_write_project_archive_is_atomic_on_limit_failure(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    output = data_dir / "result.txt"
    output.write_text("too-large", encoding="utf-8")
    archive_path = tmp_path / "project.zip"

    with pytest.raises(ProjectArchiveLimitError):
        write_project_archive(
            [{"run_id": "run", "folder_path": str(data_dir), "output_files": [str(output)]}],
            archive_path,
            application_roots=[],
            max_uncompressed_bytes=1,
        )

    assert not archive_path.exists()
    assert not (tmp_path / "project.zip.partial").exists()


def test_project_export_route_returns_structured_archive(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    output = data_dir / "result.csv"
    output.write_text("result", encoding="utf-8")
    requested = {}

    def fake_archive_records(project_id, **kwargs):
        requested["project_id"] = project_id
        requested.update(kwargs)
        return iter(
            [
                {
                    "run_id": "route-run",
                    "folder_path": str(data_dir),
                    "output_files": [str(output)],
                }
            ]
        )

    monkeypatch.setattr(routes_get, "iter_project_archive_records", fake_archive_records)

    class Handler:
        path = "/api/v1/projects/demo/export-zip"

        def __init__(self):
            self.status = None
            self.headers = {}
            self.wfile = io.BytesIO()

        def send_response(self, status):
            self.status = status

        def send_header(self, name, value):
            self.headers[name] = value

        def end_headers(self):
            return None

    handler = Handler()
    assert routes_get.dispatch_get(handler) is True
    assert handler.status == 200
    assert handler.headers["Content-Type"] == "application/zip"
    assert handler.headers["X-Electrochem-Archive-Files"] == "1"
    assert requested["project_id"] == "demo"
    with zipfile.ZipFile(io.BytesIO(handler.wfile.getvalue())) as archive:
        assert archive.namelist() == [
            "runs/0001_route-run/results/result.csv",
            "archive_manifest.json",
        ]


def test_project_export_route_returns_413_before_streaming_when_limit_is_exceeded(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    outputs = [data_dir / "one.csv", data_dir / "two.csv"]
    for output in outputs:
        output.write_text("result", encoding="utf-8")
    monkeypatch.setattr(
        routes_get,
        "iter_project_archive_records",
        lambda *_args, **_kwargs: iter(
            [
                {
                    "run_id": "route-run",
                    "folder_path": str(data_dir),
                    "output_files": [str(output) for output in outputs],
                }
            ]
        ),
    )

    class Handler:
        path = "/api/v1/projects/demo/export-zip"
        MAX_ZIP_FILES = 1
        MAX_ZIP_UNCOMPRESSED_BYTES = 1024

        def __init__(self):
            self.status = None
            self.payload = None
            self.wfile = io.BytesIO()

        def _send_json(self, status, payload):
            self.status = status
            self.payload = payload

        def send_response(self, status):
            raise AssertionError(f"streaming started unexpectedly with status {status}")

    handler = Handler()
    assert routes_get.dispatch_get(handler) is True
    assert handler.status == 413
    assert handler.payload["status"] == "error"
    assert "文件数" in handler.payload["message"]
    assert handler.wfile.getvalue() == b""


def test_real_local_processing_exports_outputs_and_source_after_runtime_restart(tmp_path, monkeypatch):
    from electrochem_v6.core.process_service import process_folder
    from electrochem_v6.store.runtime import get_database, reset_runtime

    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    reset_runtime()
    source_dir = tmp_path / "input"
    source_dir.mkdir()
    source = source_dir / "CV_demo.txt"
    source.write_text("Potential Current\n0 0\n0.2 0.0004\n0.4 0.001\n0.6 0.0003\n0.8 -0.0002\n", encoding="utf-8")
    second_dir = tmp_path / "separate-input"
    second_dir.mkdir()
    second_source = second_dir / "CV_external.txt"
    second_source.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    try:
        result = process_folder({
            "folder_path": str(source_dir), "data_types": ["CV"],
            "input_files": [str(source), str(second_source)], "project_name": "archive integration",
        })
        assert result["status"] == "success"
        record = get_database().get_all_history_records()[0]
        assert record["folder_path"] == str(source_dir.resolve())
        project_id = record["project_id"]
        reset_runtime()
        records = list(get_database().iter_history_archive_records(project_id=project_id))
        assert records[0]["archive_roots"]["input_roots"] == [str(source_dir.resolve()), str(second_dir.resolve())]
        archive_result = build_project_archive(records)
        with zipfile.ZipFile(io.BytesIO(archive_result.data)) as archive:
            names = archive.namelist()
            assert any(name.endswith("/source/CV_demo.txt") for name in names)
            assert any(name.endswith("/source/CV_external.txt") for name in names)
            assert any(name.endswith("/results/processing_results.csv") for name in names)
            assert any(name.endswith("/results/run_manifest.json") for name in names)
        assert archive_result.file_count == len(record["output_files"]) + 2
        assert archive_result.skipped_files == ()
        unrelated = tmp_path / "unrelated.txt"
        unrelated.write_text("must not export", encoding="utf-8")
        records[0]["output_files"].append(str(unrelated))
        guarded_archive = build_project_archive(records)
        assert str(unrelated.resolve()) in guarded_archive.skipped_files
    finally:
        reset_runtime()


def test_legacy_missing_folder_recovers_default_run_outputs_without_trusting_external_paths(tmp_path):
    data = tmp_path / "data"
    source = data / "nested" / "CV_demo.txt"
    source.parent.mkdir(parents=True)
    source.write_text("source")
    output = data / "electrochem_outputs" / "20260907_120000_12345678" / "result.csv"
    output.parent.mkdir(parents=True)
    output.write_text("result")
    unrelated = tmp_path / "private.txt"
    unrelated.write_text("must not export")
    result = build_project_archive([{
        "run_id": "12345678abcdef", "file_path": str(source), "folder_path": None,
        "output_files": [str(output), str(unrelated)],
    }], application_roots=[])
    with zipfile.ZipFile(io.BytesIO(result.data)) as archive:
        names = archive.namelist()
        assert any(name.endswith("/source/CV_demo.txt") for name in names)
        assert any(name.endswith("/results/result.csv") for name in names)
        assert not any(name.endswith("private.txt") for name in names)
    assert result.skipped_files == (str(unrelated.resolve()),)
