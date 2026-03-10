import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
REPO = ROOT.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from electrochem_v6.agent.tool_executor import (  # noqa: E402
    tool_get_current_compare_selection,
    tool_get_current_project_history,
    tool_get_current_project_summary,
)
from electrochem_v6.store.legacy_runtime import get_history_manager_v6  # noqa: E402
from electrochem_v6.store.projects import create_project  # noqa: E402


def test_v6_agent_tools_query_current_project(tmp_path):
    old_projects = os.environ.get("ELECTROCHEM_V6_PROJECTS_FILE")
    old_history = os.environ.get("ELECTROCHEM_V6_HISTORY_FILE")
    old_conv = os.environ.get("ELECTROCHEM_V6_CONVERSATION_FILE")
    try:
        os.environ["ELECTROCHEM_V6_PROJECTS_FILE"] = str(tmp_path / "projects.json")
        os.environ["ELECTROCHEM_V6_HISTORY_FILE"] = str(tmp_path / "history.json")
        os.environ["ELECTROCHEM_V6_CONVERSATION_FILE"] = str(tmp_path / "conversation.json")

        created = create_project("agent_demo_project", description="tool test")
        assert created.get("status") == "success"
        project_id = created.get("project_id")
        assert project_id

        hist = get_history_manager_v6()
        hist.add_record(
            {
                "timestamp": "2026-02-28 20:00:00",
                "sample_name": "sample_a",
                "file_name": "LSV_a",
                "file_path": str(tmp_path / "sample_a.txt"),
                "type": "LSV",
                "status": "success",
                "project_id": project_id,
                "project_name": "agent_demo_project",
                "results": {
                    "overpotential_10": 310.0,
                    "potential_10": 0.401,
                    "potential_at_10.0": 0.401,
                    "tafel_slope": 82.0,
                },
            }
        )
        hist.add_record(
            {
                "timestamp": "2026-02-28 20:05:00",
                "sample_name": "sample_b",
                "file_name": "LSV_b",
                "file_path": str(tmp_path / "sample_b.txt"),
                "type": "LSV",
                "status": "success",
                "project_id": project_id,
                "project_name": "agent_demo_project",
                "results": {
                    "overpotential_10": 295.0,
                    "potential_10": 0.389,
                    "potential_at_10.0": 0.389,
                    "tafel_slope": 78.0,
                },
            }
        )
        hist.add_record(
            {
                "timestamp": "2026-02-28 20:06:00",
                "sample_name": "sample_b",
                "file_name": "CV_b",
                "file_path": str(tmp_path / "cv_b.txt"),
                "type": "CV",
                "status": "success",
                "project_id": project_id,
                "project_name": "agent_demo_project",
                "results": {},
            }
        )

        summary = tool_get_current_project_summary(project_name="agent_demo_project")
        assert summary.get("success") is True
        assert summary.get("project", {}).get("id") == project_id
        assert summary.get("stats", {}).get("lsv_count") == 2
        assert len(summary.get("top_lsv_samples") or []) == 2
        assert summary.get("top_lsv_samples")[0].get("sample_name") == "sample_b"

        history = tool_get_current_project_history(project_name="agent_demo_project", record_type="LSV", limit=5)
        assert history.get("success") is True
        assert history.get("returned_count") == 2
        assert all(item.get("type") == "LSV" for item in (history.get("records") or []))

        compare = tool_get_current_compare_selection(project_name="agent_demo_project", sample_names=["sample_a"])
        assert compare.get("success") is True
        rows = compare.get("compare_rows") or []
        assert len(rows) == 1
        assert rows[0].get("sample_name") == "sample_a"
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
