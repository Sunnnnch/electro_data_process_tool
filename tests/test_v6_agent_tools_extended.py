"""Tests for agent tools — tools_analysis, tool_executor basics."""
import json

# ── tools_analysis ─────────────────────────────────────────────────────────

class TestToolReadQualityReport:
    def test_no_reports_found(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from electrochem_v6.agent.tools_analysis import tool_read_quality_report
        result = tool_read_quality_report()
        assert result["success"] is False

    def test_reads_quality_report(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        report = {
            "quality_summary": {"total_files": 3, "passed": 2, "warnings": 1, "failed": 0},
            "files": [
                {"filename": "a.txt", "is_valid": True},
                {"filename": "b.txt", "is_valid": True, "warnings": ["noisy"]},
                {"filename": "c.txt", "is_valid": True},
            ],
        }
        rpath = tmp_path / "quality_report.json"
        rpath.write_text(json.dumps(report), encoding="utf-8")

        from electrochem_v6.agent.tools_analysis import tool_read_quality_report
        result = tool_read_quality_report()
        assert result["success"] is True
        assert result["summary"]["total_files"] == 3


class TestToolAnalyzeProcessingResults:
    def test_quality_only(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from electrochem_v6.agent.tools_analysis import tool_analyze_processing_results
        result = tool_analyze_processing_results(include_quality=True, include_performance=False)
        assert "components" in result

    def test_no_crash_when_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from electrochem_v6.agent.tools_analysis import tool_analyze_processing_results
        result = tool_analyze_processing_results(include_quality=False, include_performance=False)
        assert result["success"] is True


# ── tool_executor basic tool functions ─────────────────────────────────────

class TestToolQueryLsvSummary:
    def test_returns_dict(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # Setup minimal environment
        monkeypatch.setenv("ELECTROCHEM_V6_PROJECTS_FILE", str(tmp_path / "proj.json"))
        monkeypatch.setenv("ELECTROCHEM_V6_HISTORY_FILE", str(tmp_path / "hist.json"))
        (tmp_path / "proj.json").write_text("[]", encoding="utf-8")
        (tmp_path / "hist.json").write_text("[]", encoding="utf-8")

        from electrochem_v6.agent.tool_executor import tool_query_lsv_summary
        result = tool_query_lsv_summary()
        assert isinstance(result, dict)

    def test_with_top_n(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("ELECTROCHEM_V6_PROJECTS_FILE", str(tmp_path / "proj.json"))
        monkeypatch.setenv("ELECTROCHEM_V6_HISTORY_FILE", str(tmp_path / "hist.json"))
        (tmp_path / "proj.json").write_text("[]", encoding="utf-8")
        (tmp_path / "hist.json").write_text("[]", encoding="utf-8")

        from electrochem_v6.agent.tool_executor import tool_query_lsv_summary
        result = tool_query_lsv_summary(top_n=3)
        assert isinstance(result, dict)


class TestToolFindBestCatalysts:
    def test_returns_dict(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("ELECTROCHEM_V6_PROJECTS_FILE", str(tmp_path / "proj.json"))
        monkeypatch.setenv("ELECTROCHEM_V6_HISTORY_FILE", str(tmp_path / "hist.json"))
        (tmp_path / "proj.json").write_text("[]", encoding="utf-8")
        (tmp_path / "hist.json").write_text("[]", encoding="utf-8")

        from electrochem_v6.agent.tool_executor import tool_find_best_catalysts
        result = tool_find_best_catalysts()
        assert isinstance(result, dict)


# ── execute_tool dispatcher ────────────────────────────────────────────────

class TestExecuteTool:
    def test_unknown_tool(self):
        from electrochem_v6.agent.tool_executor import execute_tool
        result = execute_tool("nonexistent_tool", {})
        assert result.get("success") is False
        assert "未知工具" in result.get("error", "")

    def test_invalid_json_arguments(self):
        from electrochem_v6.agent.tool_executor import execute_tool
        result = execute_tool("query_lsv_summary", "not-valid-json{")
        assert result.get("success") is False
        assert "参数解析失败" in result.get("error", "")

    def test_dict_arguments_accepted(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ELECTROCHEM_V6_PROJECTS_FILE", str(tmp_path / "p.json"))
        monkeypatch.setenv("ELECTROCHEM_V6_HISTORY_FILE", str(tmp_path / "h.json"))
        (tmp_path / "p.json").write_text("[]", encoding="utf-8")
        (tmp_path / "h.json").write_text("[]", encoding="utf-8")

        from electrochem_v6.agent.tool_executor import execute_tool
        result = execute_tool("query_lsv_summary", {"top_n": 3})
        assert isinstance(result, dict)

    def test_json_string_arguments(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ELECTROCHEM_V6_PROJECTS_FILE", str(tmp_path / "p.json"))
        monkeypatch.setenv("ELECTROCHEM_V6_HISTORY_FILE", str(tmp_path / "h.json"))
        (tmp_path / "p.json").write_text("[]", encoding="utf-8")
        (tmp_path / "h.json").write_text("[]", encoding="utf-8")

        from electrochem_v6.agent.tool_executor import execute_tool
        result = execute_tool("query_lsv_summary", '{"top_n": 5}')
        assert isinstance(result, dict)

    def test_tool_exception_wrapped(self, monkeypatch):
        from electrochem_v6.agent import tool_executor

        def _bomb(**kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(tool_executor, "tool_query_lsv_summary", _bomb)

        result = tool_executor.execute_tool("query_lsv_summary", {})
        assert result.get("success") is False
        assert "boom" in result.get("error", "")

    def test_get_catalyst_info_dispatched(self):
        from electrochem_v6.agent.tool_executor import execute_tool
        result = execute_tool("get_catalyst_info", {"name": "Pt/C"})
        assert isinstance(result, dict)
