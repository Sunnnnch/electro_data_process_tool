"""Tests for agent/tools_projects.py — project tools & auto-processing."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_PROJECTS_FILE", str(tmp_path / "projects.json"))
    monkeypatch.setenv("ELECTROCHEM_V6_HISTORY_FILE", str(tmp_path / "history.json"))
    monkeypatch.setenv("ELECTROCHEM_V6_CONVERSATION_FILE", str(tmp_path / "conv.json"))


# ── _resolve_v6_project ──────────────────────────────────────────

class TestResolveV6Project:
    def test_no_arguments(self):
        from electrochem_v6.agent.tools_projects import _resolve_v6_project
        proj, err = _resolve_v6_project()
        assert proj is None
        assert err is not None

    def test_by_name(self, tmp_path):
        from electrochem_v6.agent.tools_projects import _resolve_v6_project
        from electrochem_v6.store.projects import create_project
        create_project("Alpha", description="test")
        proj, err = _resolve_v6_project(project_name="Alpha")
        assert proj is not None
        assert err is None
        assert proj["name"] == "Alpha"

    def test_by_name_casefold(self, tmp_path):
        from electrochem_v6.agent.tools_projects import _resolve_v6_project
        from electrochem_v6.store.projects import create_project
        create_project("MyProject")
        proj, err = _resolve_v6_project(project_name="myproject")
        assert proj is not None

    def test_by_id(self, tmp_path):
        from electrochem_v6.agent.tools_projects import _resolve_v6_project
        from electrochem_v6.store.projects import create_project
        result = create_project("Beta")
        pid = result["project_id"]
        proj, err = _resolve_v6_project(project_id=pid)
        assert proj is not None
        assert proj["id"] == pid

    def test_archived_project_remains_available_for_read_only_queries(self):
        from electrochem_v6.agent.tools_projects import _resolve_v6_project
        from electrochem_v6.store.projects import create_project, delete_project

        created = create_project("Archived analysis")
        assert delete_project(created["project_id"])["status"] == "success"

        project, err = _resolve_v6_project(project_name="Archived analysis")
        assert err is None
        assert project is not None
        assert project["status"] == "archived"

    def test_not_found(self):
        from electrochem_v6.agent.tools_projects import _resolve_v6_project
        proj, err = _resolve_v6_project(project_name="NonExistent")
        assert proj is None
        assert "未找到" in err


# ── tool_create_project ───────────────────────────────────────────

class TestToolCreateProject:
    def test_create(self):
        from electrochem_v6.agent.tools_projects import tool_create_project
        result = tool_create_project(name="TestProj", description="desc")
        assert result.get("success") is True
        assert result.get("project_id")

    def test_create_duplicate_name(self):
        from electrochem_v6.agent.tools_projects import tool_create_project
        tool_create_project(name="Dup")
        result2 = tool_create_project(name="Dup")
        # Should still succeed (creates with new ID)
        assert isinstance(result2, dict)


# ── tool_get_current_project_summary ──────────────────────────────

class TestToolGetCurrentProjectSummary:
    def test_no_project(self):
        from electrochem_v6.agent.tools_projects import tool_get_current_project_summary
        result = tool_get_current_project_summary(project_name="Ghost")
        assert result.get("success") is False

    def test_with_project(self):
        from electrochem_v6.agent.tools_projects import tool_get_current_project_summary
        from electrochem_v6.store.projects import create_project
        created = create_project("SummaryProj")
        pid = created["project_id"]
        result = tool_get_current_project_summary(project_id=pid)
        assert result.get("success") is True
        assert "stats" in result


# ── tool_get_processing_history ───────────────────────────────────

class TestToolGetProcessingHistory:
    def test_empty_history(self):
        from electrochem_v6.agent.tools_projects import tool_get_processing_history
        result = tool_get_processing_history()
        assert result.get("success") is True
        assert isinstance(result.get("records"), list)


# ── tool_auto_process_with_smart_params ───────────────────────────


def _service_success(data_type, *, project_id=None):
    return {
        "status": "success",
        "result": {
            "processing": {
                "output_files": [f"{data_type}_results.csv"],
                "matched_counts": {data_type: 1},
            },
            "raw": {
                "module_runs": [
                    {"data_type": data_type, "matched": 1, "processed": 1, "status": "success"}
                ]
            },
            "quality_summary": {"total_files": 1, "passed": 1},
            "project_id": project_id,
        },
    }

class TestToolAutoProcessWithSmartParams:
    @staticmethod
    def scientific_params(data_type="LSV"):
        prefix = data_type.lower()
        return {"area": 1.0, "potential_mode": "manual", "potential_offset": 0.0,
                "use_abs_current": True, "ir_compensation_enabled": False,
                f"{prefix}_potential_column": 1, f"{prefix}_current_column": 2,
                f"{prefix}_potential_unit": "v", f"{prefix}_current_unit": "a"}
    def test_empty_folder(self, tmp_path):
        from electrochem_v6.agent.tools_projects import tool_auto_process_with_smart_params
        empty = tmp_path / "empty_data"
        empty.mkdir()
        result = tool_auto_process_with_smart_params(
            folder_path=str(empty), data_type="LSV"
        )
        assert result.get("success") is False

    def test_unsupported_data_type(self, tmp_path):
        from electrochem_v6.agent.tools_projects import tool_auto_process_with_smart_params
        folder = tmp_path / "data"
        folder.mkdir()
        (folder / "test.txt").write_text("0.1\t0.001\n0.2\t0.002\n", encoding="utf-8")
        result = tool_auto_process_with_smart_params(
            folder_path=str(folder), data_type="UNKNOWN"
        )
        assert result.get("success") is False
        assert "Unsupported" in result.get("error", "")

    def test_lsv_processing_with_mock(self, tmp_path):
        from electrochem_v6.agent.tools_projects import tool_auto_process_with_smart_params

        folder = tmp_path / "lsv_data"
        folder.mkdir()
        # Create a minimal LSV file
        lines = [f"{0.01*i:.4f}\t{1e-6 * (2.718 ** (5*0.01*i)):.10f}" for i in range(30)]
        (folder / "LSV_sample.txt").write_text("\n".join(lines), encoding="utf-8")

        with patch("electrochem_v6.core.process_service.process_folder") as mock_process:
            mock_process.return_value = _service_success("LSV")
            result = tool_auto_process_with_smart_params(
                folder_path=str(folder),
                data_type="LSV",
                target_current="10",
                tafel_range="1-10",
                extra_gui_params=self.scientific_params(),
            )
            assert result.get("success") is True
            assert mock_process.called
            payload = mock_process.call_args[0][0]
            assert payload["data_types"] == ["LSV"]
            assert "lsv_enabled" not in payload["params"]
            assert payload["params"]["tafel_enabled"] is True
            assert payload["params"]["lsv_target_current"] == "10"

    def test_cv_processing_with_mock(self, tmp_path):
        from electrochem_v6.agent.tools_projects import tool_auto_process_with_smart_params

        folder = tmp_path / "cv_data"
        folder.mkdir()
        (folder / "CV_test.txt").write_text("0.1\t0.001\n0.2\t0.002\n", encoding="utf-8")

        with patch("electrochem_v6.core.process_service.process_folder") as mock_process:
            mock_process.return_value = _service_success("CV")
            result = tool_auto_process_with_smart_params(
                folder_path=str(folder), data_type="CV", extra_gui_params=self.scientific_params("CV")
            )
            assert result.get("success") is True
            payload = mock_process.call_args[0][0]
            assert "cv_enabled" not in payload["params"]

    def test_with_project_name(self, tmp_path):
        from electrochem_v6.agent.tools_projects import tool_auto_process_with_smart_params

        folder = tmp_path / "proj_data"
        folder.mkdir()
        (folder / "LSV_a.txt").write_text("0.1\t0.001\n0.2\t0.002\n", encoding="utf-8")

        with patch("electrochem_v6.core.process_service.process_folder") as mock_process:
            mock_process.return_value = _service_success("LSV", project_id="project-1")
            result = tool_auto_process_with_smart_params(
                folder_path=str(folder),
                data_type="LSV",
                project_name="AutoProject",
                extra_gui_params=self.scientific_params(),
            )
            assert result.get("success") is True
            payload = mock_process.call_args[0][0]
            assert payload["project_name"] == "AutoProject"
            assert result["project_id"] == "project-1"

    def test_lsv_processing_uses_module_registry_end_to_end(self, tmp_path):
        from electrochem_v6.agent.tools_projects import tool_auto_process_with_smart_params

        folder = tmp_path / "lsv_runtime"
        folder.mkdir()
        lines = [
            f"{index * 0.02:.4f}\t{1e-6 * (2.718 ** (4 * index * 0.02)):.10f}"
            for index in range(80)
        ]
        (folder / "LSV_runtime.txt").write_text("\n".join(lines), encoding="utf-8")

        result = tool_auto_process_with_smart_params(
            folder_path=str(folder),
            data_type="LSV",
            target_current="1",
            extra_gui_params=self.scientific_params(),
        )

        assert result["success"] is True
        assert result["processing"]["processed_count"] == 1
        outputs = [Path(item) for item in result["processing"]["output_files"]]
        summary_path = next(item for item in outputs if item.name == "summary.json")
        assert any(item.name == "processing_results.csv" for item in outputs)
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary["runtime"] == "module_registry"
        assert summary["module_runs"][0]["data_type"] == "LSV"
