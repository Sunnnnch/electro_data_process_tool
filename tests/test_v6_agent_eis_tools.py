"""Real assistant dispatch uses the EIS registry and retains compact diagnostics."""

from __future__ import annotations

import json

import numpy as np
import pytest
from jsonschema import validate

from electrochem_v6.agent.actions import finish_action_collection, start_action_collection
from electrochem_v6.agent.request_context import reset_professional_mode_context, set_professional_mode_context
from electrochem_v6.agent.tool_executor import execute_tool
from electrochem_v6.agent.tools import ALL_TOOLS
from electrochem_v6.agent.tools_projects import _simplify_v6_history_record
from electrochem_v6.core.processing_eis_calc import EIS_CIRCUIT_MODELS
from electrochem_v6.store.run_recipes import get_run_recipe
from electrochem_v6.store.runtime import get_database, reset_runtime


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    for suffix in ("HISTORY", "PROJECTS", "CONVERSATION", "TEMPLATE", "QUALITY_REPORT"):
        monkeypatch.delenv(f"ELECTROCHEM_V6_{suffix}_FILE", raising=False)
    reset_runtime()
    yield
    reset_runtime()


def _source_parameters():
    return {"eis_frequency_column": 1, "eis_zreal_column": 2, "eis_zimag_column": 3,
            "eis_frequency_unit": "hz", "eis_impedance_unit": "ohm", "eis_zimag_convention": "z_imaginary"}


def test_schema_discovery_is_a_read_only_dispatched_tool_with_six_models(monkeypatch):
    monkeypatch.setattr("electrochem_v6.store.runtime.get_database", lambda: pytest.fail("Schema discovery must not read user data"))
    declared = {tool["function"]["name"]: tool["function"] for tool in ALL_TOOLS}
    validate({"data_types": ["EIS"]}, declared["get_processing_schema"]["parameters"])
    result = execute_tool("get_processing_schema", {"data_types": ["EIS"]})
    assert result["success"] is True
    parameters = {item["key"]: item for item in result["schema"]["parameters"]}
    assert parameters["eis_circuit_model"]["options"] == list(EIS_CIRCUIT_MODELS)
    assert parameters["eis_fit_weighting"]["options"] == ["uniform", "modulus"]
    assert {"eis_kk_check", "eis_fit_frequency_min_hz", "eis_fit_frequency_max_hz"} <= parameters.keys()
    assert execute_tool("get_processing_schema", {"data_types": ["CV"]})["success"] is True
    for invalid in (["UNKNOWN"], "EIS", [], ["EIS", "EIS"]):
        assert execute_tool("get_processing_schema", {"data_types": invalid})["success"] is False


@pytest.mark.parametrize("model", list(EIS_CIRCUIT_MODELS))
def test_discovered_models_work_in_existing_parameter_proposals(model):
    before = {**_source_parameters(), "eis_randles_fit": False, "eis_circuit_model": "randles_rc",
              "eis_kk_check": False, "eis_fit_weighting": "uniform"}
    context_token = set_professional_mode_context({"data_types": ["EIS"], "parameters": before})
    action_token = start_action_collection()
    try:
        changes = {"eis_randles_fit": True, "eis_circuit_model": model, "eis_kk_check": True,
                   "eis_fit_weighting": "modulus", "eis_fit_frequency_min_hz": .5, "eis_fit_frequency_max_hz": 50000}
        response = execute_tool("propose_parameter_changes", {"changes": [
            {"key": key, "value": value, "reason": "用户明确选择的EIS设置"} for key, value in changes.items()
        ]})
        assert response["success"] is True, response
        assert response["executed"] is False
        card = response["action_card"]
        effective = {**before, **{item["key"]: item["after"] for item in card["changes"]}}
        assert effective["eis_circuit_model"] == model
        assert effective["eis_kk_check"] is True
        assert before["eis_randles_fit"] is False
    finally:
        finish_action_collection(action_token)
        reset_professional_mode_context(context_token)


def _all_keys(value):
    if isinstance(value, dict):
        return set(value) | set().union(*(_all_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_all_keys(item) for item in value))
    return set()


def test_auto_tool_accepts_eis_parameters_and_project_history_keeps_real_compact_diagnostics(tmp_path):
    folder = tmp_path / "source"
    folder.mkdir()
    frequency = np.logspace(-1, 5, 60)
    omega = 2 * np.pi * frequency
    impedance = 7 + 1 / (1 / 85 + 3e-5 * (1j * omega) ** .82)
    source = folder / "EIS_assistant.txt"
    source.write_text("Frequency Zreal Zimag\n" + "\n".join(
        f"{f:.17g} {z.real:.17g} {z.imag:.17g}" for f, z in zip(frequency, impedance)
    ))
    arguments = {"folder_path": str(folder), "data_type": "EIS", "project_name": "assistant EIS",
                 "extra_gui_params": {**_source_parameters(), "eis_randles_fit": True,
                     "eis_circuit_model": "randles_cpe", "eis_kk_check": True, "eis_fit_weighting": "modulus",
                     "eis_fit_frequency_min_hz": .1, "eis_fit_frequency_max_hz": 100000,
                     "plot_nyquist": False, "plot_bode": False}}
    tool = next(item["function"] for item in ALL_TOOLS if item["function"]["name"] == "auto_process_with_smart_params")
    validate(arguments, tool["parameters"])
    pending = execute_tool("auto_process_with_smart_params", arguments)
    assert pending["confirmation_required"] is True  # Existing confirmation is preserved, not bypassed.
    response = execute_tool("auto_process_with_smart_params", arguments, approved=True)
    assert response["success"] is True, response
    assert response["effective_params"]["eis_circuit_model"] == "randles_cpe"
    assert response["effective_params"]["eis_kk_check"] is True
    recipe = get_run_recipe(response["run_id"])
    record = get_database().get_history_record(recipe["record_keys"][0])
    project_id = record["project_id"]
    result = execute_tool("get_current_project_history", {"project_id": project_id, "record_type": "EIS"})
    assert result["success"] is True
    brief = result["records"][0]
    assert brief["record_key"] == recipe["record_keys"][0]
    assert brief["run_id"] == response["run_id"]
    assert brief["results"]["CPE_n"] == pytest.approx(.82, abs=.01)
    fit = brief["eis_analysis"]["fit"]
    assert fit["parameters"]["n"] == pytest.approx(.82, abs=.01)
    assert fit["parameter_units"]["Q"] == "S*s^n"
    assert fit["parameter_ci95"] == record["eis_analysis"]["fit"]["parameter_ci95"]
    assert brief["eis_analysis"]["kk"]["status"] == "consistent"
    assert brief["eis_analysis"]["frequency_selection"]["interval"] == "closed"
    assert brief["eis_analysis"]["point_arrays_omitted"] is True
    excluded = {"frequency_hz", "z_fit_real", "z_fit_imag", "residual_real", "residual_imag",
                "residual_real_ohm", "residual_imag_ohm", "selected_indices", "fit_indices", "candidates"}
    assert not (excluded & _all_keys(brief))
    project = execute_tool("get_current_project_summary", {"project_id": project_id})
    assert project["recent_history"][0]["eis_analysis"] == brief["eis_analysis"]
    full = execute_tool("get_processing_history", {"project_id": project_id, "record_type": "EIS"})
    assert len(full["records"][0]["eis_analysis"]["kk"]["residual_real"]) > 0
    json.dumps(brief, allow_nan=False)


def test_legacy_eis_metrics_and_non_eis_summaries_keep_their_meaning():
    old_eis = _simplify_v6_history_record({"type": "EIS", "results": {"Rs": 0, "Rct": 85, "Cdl": 1e-5}})
    assert old_eis["results"] == {"Rs": 0, "Rct": 85, "Cdl": 1e-5}
    assert "eis_analysis" not in old_eis  # No invented acceptance or uncertainty for old records.
    lsv = _simplify_v6_history_record({"type": "LSV", "results": {"overpotential_10": 0, "tafel_slope": 70}})
    assert lsv["results"] == {"overpotential_10": 0, "potential_10": None, "potential_at_10.0": None, "tafel_slope": 70}
    assert "eis_analysis" not in lsv
