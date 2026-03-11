import json
import os
from concurrent.futures import ThreadPoolExecutor

from electrochem_v6.store.projects import (
    _sanitize_description,
    _validate_project_name,
    get_or_create_project_id_by_name,
)


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


# ── Project input validation tests ─────────────────────────────────────────

class TestValidateProjectName:
    def test_normal_name(self):
        name, err = _validate_project_name("My Project")
        assert name == "My Project"
        assert err is None

    def test_empty_name(self):
        name, err = _validate_project_name("")
        assert name is None
        assert err is not None

    def test_none_name(self):
        name, err = _validate_project_name(None)
        assert name is None
        assert err is not None

    def test_whitespace_only(self):
        name, err = _validate_project_name("   ")
        assert name is None
        assert err is not None

    def test_control_chars_stripped(self):
        name, err = _validate_project_name("proj\x00ect\x07\x1fname")
        assert name == "projectname"
        assert err is None

    def test_too_long(self):
        name, err = _validate_project_name("a" * 200)
        assert name is None
        assert "128" in err

    def test_unicode_ok(self):
        name, err = _validate_project_name("电化学项目-1")
        assert name == "电化学项目-1"
        assert err is None


class TestSanitizeDescription:
    def test_normal(self):
        assert _sanitize_description("A description") == "A description"

    def test_control_chars(self):
        assert _sanitize_description("foo\x00bar\x1f") == "foobar"

    def test_truncated(self):
        assert len(_sanitize_description("x" * 2000)) == 1024

    def test_none(self):
        assert _sanitize_description(None) == ""
