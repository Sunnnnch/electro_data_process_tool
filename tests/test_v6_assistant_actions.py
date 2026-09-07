"""Structured proposals survive model calls and conversation persistence."""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from electrochem_v6.agent.actions import finish_action_collection, input_path_signature, start_action_collection
from electrochem_v6.agent.agent_controller import AgentController
from electrochem_v6.agent.request_context import reset_professional_mode_context, set_professional_mode_context
from electrochem_v6.agent.service import AgentService
from electrochem_v6.agent.tool_executor import execute_tool
from electrochem_v6.core.process_service import _build_gui_vars, process_folder
from electrochem_v6.store.conversations import get_conversation
from electrochem_v6.store.run_recipes import get_run_recipe
from electrochem_v6.store.runtime import get_database, reset_runtime


@pytest.fixture
def action_data(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    for key, filename in {"HISTORY": "history", "PROJECTS": "projects", "CONVERSATION": "conversations", "TEMPLATE": "templates", "QUALITY_REPORT": "quality"}.items():
        monkeypatch.setenv(f"ELECTROCHEM_V6_{key}_FILE", str(tmp_path / f"{filename}.json"))
    reset_runtime()
    database = get_database()
    for project in ("alpha", "beta"):
        database.create_project({"id": project, "name": project, "status": "active", "created_at": "2026-09-07", "updated_at": "2026-09-07"})
    folder = tmp_path / "sources"
    folder.mkdir()
    source = folder / "CV_demo.txt"
    source.write_text("Potential Current\n0 0\n0.2 0.0004\n0.4 0.001\n0.6 0.0003\n0.8 -0.0002\n")
    runs = []
    for project, area in (("alpha", 1), ("alpha", 2), ("beta", 3)):
        result = process_folder({"folder_path": str(folder), "data_types": ["CV"], "project_id": project, "params": {"area": area}})
        assert result["status"] == "success", result
        runs.append(get_run_recipe(result["result"]["manifest"]["run"]["run_id"]))
    context = {"data_types": ["CV"], "parameters": _build_gui_vars(["CV"], {"params": {"area": 1}}),
               "data_source": {"mode": "selected_files", "files": [{"name": source.name}]},
               "action_context": {"project_id": "alpha", "record_keys": [runs[0]["record_keys"][0], runs[1]["record_keys"][0]], "run_id": runs[0]["run_id"], "parameter_signature": "explicit-source-signature"}}
    yield {"runs": runs, "context": context, "source": source}
    reset_runtime()


def model_service(monkeypatch, calls):
    client = MagicMock()
    client.stream_chat.side_effect = NotImplementedError
    client.chat.side_effect = [{"role": "assistant", "content": "", "tool_calls": [
        {"id": f"call-{index}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
        for index, (name, args) in enumerate(calls)
    ]}, {"content": "已准备操作卡，尚未执行。"}]
    controller = AgentController(client)
    service = AgentService()
    monkeypatch.setattr(service, "_create_agent", lambda *args, **kwargs: (controller, "mock", "mock"))
    return service, controller


def create_all_cards(data, monkeypatch):
    context = data["context"]
    keys = context["action_context"]["record_keys"]
    service, controller = model_service(monkeypatch, [
        ("propose_parameter_changes", {"changes": [{"key": "area", "value": 2, "reason": "使用用户确认的电极面积"}]}),
        ("prepare_record_comparison", {"record_keys": keys}),
        ("prepare_run_replay", {"run_id": data["runs"][0]["run_id"], "params": {"area": 2}}),
        ("prepare_result_report", {"record_keys": keys}),
    ])
    result = service.chat(message="准备这四项操作", professional_context=context)
    assert result["status"] == "success", result
    tool_results = [json.loads(item["content"]) for item in controller.get_history() if item.get("role") == "tool"]
    assert all(item["success"] for item in tool_results), tool_results
    return result


def test_mock_model_cards_persist_and_restore_without_processing(action_data, monkeypatch):
    before = len(get_database().get_all_history_records())
    result = create_all_cards(action_data, monkeypatch)
    assert [item["kind"] for item in result["action_cards"]] == ["parameter_changes", "compare_records", "replay_run", "report_records"]
    assert not result["pending_approvals"]
    restored = get_conversation(result["conversation_id"])
    cards = restored["messages"][-1]["metadata"]["action_cards"]
    assert cards == result["action_cards"]
    restored_again = AgentService().annotate_conversation_approvals(restored)
    assert restored_again["messages"][-1]["metadata"]["action_cards"] == cards
    assert len(get_database().get_all_history_records()) == before
    assert cards[0]["changes"][0]["before"] == 1
    assert cards[0]["changes"][0]["after"] == 2
    assert cards[3]["record_keys"] == action_data["context"]["action_context"]["record_keys"]
    assert cards[2]["preview"]["can_replay"] is True


@pytest.mark.parametrize("tool,args", [
    ("propose_parameter_changes", {"changes": [{"key": "ir_eis_file", "value": "C:/arbitrary.txt", "reason": "wrong source"}]}),
    ("propose_parameter_changes", {"changes": [{"key": "area", "value": "not a number", "reason": "invalid"}]}),
    ("prepare_result_report", {"record_keys": []}),
    ("prepare_record_comparison", {"record_keys": ["one"]}),
])
def test_invalid_actions_never_create_cards(action_data, tool, args):
    context_token = set_professional_mode_context(action_data["context"])
    card_token = start_action_collection()
    try:
        result = execute_tool(tool, args)
        assert result["success"] is False
    finally:
        assert finish_action_collection(card_token) == []
        reset_professional_mode_context(context_token)


def test_project_record_and_run_mismatch_never_create_cards(action_data):
    context = deepcopy(action_data["context"])
    context["action_context"]["record_keys"] = []
    foreign = action_data["runs"][2]
    token = set_professional_mode_context(context)
    cards_token = start_action_collection()
    try:
        for tool, args in (
            ("prepare_result_report", {"project_id": "beta", "record_keys": foreign["record_keys"]}),
            ("prepare_result_report", {"record_keys": foreign["record_keys"]}),
            ("prepare_run_replay", {"run_id": foreign["run_id"]}),
        ):
            assert execute_tool(tool, args)["success"] is False
    finally:
        assert finish_action_collection(cards_token) == []
        reset_professional_mode_context(token)


def test_missing_experimental_conditions_and_unverified_tafel_are_not_applicable(action_data):
    context = deepcopy(action_data["context"])
    context.update(data_types=["LSV"], parameters={"area": 1})
    token = set_professional_mode_context(context)
    cards_token = start_action_collection()
    try:
        result = execute_tool("propose_parameter_changes", {"changes": [{"key": "area", "value": 2, "reason": "known area"}]})
        assert result["recommendation_status"] == "needs_parameters"
    finally:
        assert finish_action_collection(cards_token) == []
        reset_professional_mode_context(token)
    context["parameters"] = _build_gui_vars(["LSV"], {"params": {}})
    token = set_professional_mode_context(context)
    cards_token = start_action_collection()
    try:
        result = execute_tool("propose_parameter_changes", {"changes": [{"key": "tafel_range", "value": "2-20", "reason": "unsupported guess"}]})
        assert result["success"] is False
    finally:
        assert finish_action_collection(cards_token) == []
        reset_professional_mode_context(token)


def test_finished_processing_reply_has_exact_run_entry(action_data, monkeypatch):
    controller = MagicMock()
    controller.chat.return_value = "处理已完成"
    controller.get_last_tool_calls.return_value = []
    service = AgentService()
    monkeypatch.setattr(service, "_create_agent", lambda *args, **kwargs: (controller, "mock", "mock"))
    run = action_data["runs"][0]
    result = service.chat(message="总结本次处理", processing_result={"run_id": run["run_id"]})
    card = result["action_cards"][0]
    assert card["kind"] == "open_results" and card["run_id"] == run["run_id"]
    assert card["record_keys"] == run["record_keys"] and card["project_id"] == "alpha"


def test_verified_tafel_candidate_can_form_card_but_changed_conditions_cannot(action_data):
    from test_v6_agent_scientific import source_params, write_curve

    source, _ = write_curve(action_data["source"].parent)
    context = deepcopy(action_data["context"])
    params = _build_gui_vars(["LSV"], {"params": source_params()})
    context.update(data_types=["LSV"], parameters=params)
    normalized = str(source).replace("\\", "/")
    if os.name == "nt":
        normalized = normalized.lower()
    context["action_context"]["input_path_signatures"] = [hashlib.sha256(normalized.encode("utf-8")).hexdigest()]
    token = set_professional_mode_context(context)
    cards_token = start_action_collection()
    try:
        analysis = execute_tool("analyze_data_characteristics", {"file_path": str(source), "data_type": "LSV", "params": params})
        assert analysis["recommendation_status"] == "candidates_available", analysis
        candidate = next(item for item in analysis["candidate_tafel_ranges"] if item["tafel_range"] != params["tafel_range"])
        change = {"key": "tafel_range", "value": candidate["tafel_range"], "reason": "候选区间有足够点数及跨度，仍需人工复核"}
        prepared = execute_tool("propose_parameter_changes", {"changes": [change]})
        assert prepared["success"] and prepared["executed"] is False, prepared
        card = prepared["action_card"]
        provenance = card["recommendation"]["provenance"]
        assert provenance == {"file_name": source.name, "sha256": analysis["provenance"]["sha256"]}
        assert "path" not in provenance
        assert card["recommendation"]["scope"] == "single_input"
        assert card["recommendation"]["limitations"] == analysis["limitations"]
        assert "仅此一个输入文件" in card["preview"]["warnings"][0]
        assert "共享" in card["preview"]["warnings"][1]
        stale = execute_tool("propose_parameter_changes", {"changes": [change, {"key": "area", "value": 4, "reason": "面积发生变化"}]})
        assert stale["success"] is False
    finally:
        cards = finish_action_collection(cards_token)
        reset_professional_mode_context(token)
    assert len(cards) == 1


@pytest.mark.parametrize("binding", ["missing", "empty", "malformed", "other_same_name"])
def test_tafel_candidate_cannot_apply_without_matching_selected_input(action_data, binding):
    from test_v6_agent_scientific import source_params, write_curve

    source_a, _ = write_curve(action_data["source"].parent)
    other_folder = source_a.parent / "other"
    other_folder.mkdir()
    source_b, _ = write_curve(other_folder)
    # Content and file names match; only the selected absolute path differs.
    assert source_a.name == source_b.name and source_a.read_bytes() == source_b.read_bytes()
    context = deepcopy(action_data["context"])
    params = _build_gui_vars(["LSV"], {"params": source_params()})
    context.update(data_types=["LSV"], parameters=params)
    if binding != "missing":
        context["action_context"]["input_path_signatures"] = {
            "empty": [], "malformed": [str(source_a)],
            "other_same_name": [input_path_signature(str(source_a))],
        }[binding]
    token = set_professional_mode_context(context)
    cards_token = start_action_collection()
    try:
        analysis = execute_tool("analyze_data_characteristics", {"file_path": str(source_b), "data_type": "LSV", "params": params})
        assert analysis["recommendation_status"] == "candidates_available", analysis
        candidate = next(item for item in analysis["candidate_tafel_ranges"] if item["tafel_range"] != params["tafel_range"])
        result = execute_tool("propose_parameter_changes", {"changes": [{"key": "tafel_range", "value": candidate["tafel_range"], "reason": "候选区间"}]})
        assert result["success"] is False
        assert "输入" in result["error"]
        # This new requirement does not block an ordinary, explicit parameter change.
        ordinary = execute_tool("propose_parameter_changes", {"changes": [{"key": "area", "value": 4, "reason": "用户确认的新面积"}]})
        assert ordinary["success"] is True, ordinary
    finally:
        cards = finish_action_collection(cards_token)
        reset_professional_mode_context(token)
    assert len(cards) == 1 and cards[0]["changes"][0]["key"] == "area"


def test_path_signatures_match_browser_windows_normalization_and_preserve_posix_case():
    expected = hashlib.sha256("c:/data/experiment/lsv.csv".encode()).hexdigest()
    assert input_path_signature(r"C:\Data\Experiment\LSV.csv") == expected
    assert input_path_signature("c:/data/./experiment/../experiment/lsv.csv") == expected
    assert input_path_signature(r"\\SERVER\SHARE\A\LSV.csv") == input_path_signature("//server/share/a/lsv.csv")
    assert input_path_signature("/data/LSV.csv") != input_path_signature("/data/lsv.csv")
    with pytest.raises(ValueError, match="绝对路径"):
        input_path_signature("LSV.csv")


def test_lsv_summary_orders_missing_nonfinite_and_zero_without_claiming_unknown_best(monkeypatch):
    from electrochem_v6.agent.tool_executor import tool_find_best_catalysts, tool_query_lsv_summary

    store = MagicMock()
    samples = [{"sample_name": "unknown", "overpotential_10": None},
               {"sample_name": "valid", "overpotential_10": 0.2},
               {"sample_name": "nan", "overpotential_10": float("nan")},
               {"sample_name": "zero", "overpotential_10": 0}]
    store.get_lsv_summary.return_value = {"samples": samples}
    monkeypatch.setattr("electrochem_v6.store.runtime.get_history_store", lambda: store)
    result = tool_query_lsv_summary()
    assert result["success"]
    assert [item["sample_name"] for item in result["samples"]] == ["zero", "valid", "unknown", "nan"]
    assert result["unranked_samples"] == 2
    assert [item["sample_name"] for item in tool_find_best_catalysts()["best_catalysts"]] == ["zero", "valid"]
    store.get_lsv_summary.return_value = {"samples": samples[:1]}
    assert tool_find_best_catalysts()["success"] is False
