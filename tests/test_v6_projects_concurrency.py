import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from electrochem_v6.store.projects import get_or_create_project_id_by_name  # noqa: E402


def test_v6_get_or_create_project_concurrent_same_name(tmp_path):
    old_projects = os.environ.get("ELECTROCHEM_V6_PROJECTS_FILE")
    old_history = os.environ.get("ELECTROCHEM_V6_HISTORY_FILE")
    old_conv = os.environ.get("ELECTROCHEM_V6_CONVERSATION_FILE")
    try:
        projects_file = tmp_path / "projects.json"
        os.environ["ELECTROCHEM_V6_PROJECTS_FILE"] = str(projects_file)
        os.environ["ELECTROCHEM_V6_HISTORY_FILE"] = str(tmp_path / "history.json")
        os.environ["ELECTROCHEM_V6_CONVERSATION_FILE"] = str(tmp_path / "conversation.json")

        target_name = "并发测试项目"
        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(lambda _: get_or_create_project_id_by_name(target_name), range(20)))

        ids = [x for x in ids if x]
        assert ids
        assert len(set(ids)) == 1

        data = json.loads(projects_file.read_text(encoding="utf-8"))
        projects = data.get("projects") or []
        matched = [p for p in projects if p.get("name") == target_name and p.get("status", "active") == "active"]
        assert len(matched) == 1
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

