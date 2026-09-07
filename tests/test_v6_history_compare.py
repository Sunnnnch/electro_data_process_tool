"""Historical comparisons must preserve selected versions and measurement units."""

import json

import pytest

from electrochem_v6.core.history_compare import build_history_comparison, compare_history_records


def record(run="old", data_type="LSV", **results):
    return {
        "record_key": run, "run_id": run, "project_id": "project",
        "sample_name": "sample", "file_path": "sample.txt", "type": data_type,
        "results": results,
    }


def by_key(comparison):
    return {metric["key"]: metric for metric in comparison["metrics"]}


def test_cpe_q_is_not_subtracted_when_exponent_changes_its_dimensions():
    comparison = build_history_comparison(
        record(data_type="EIS", CPE_Q=0.001, CPE_n=0.8),
        record("new", data_type="EIS", CPE_Q=0.002, CPE_n=0.9),
    )
    assert by_key(comparison)["CPE_Q"]["delta"] is None
    assert by_key(comparison)["CPE_Q"]["status"] == "unit_mismatch"
    assert by_key(comparison)["CPE_n"]["delta"] == pytest.approx(0.1)


def test_target_aliases_are_deduplicated_and_missing_is_not_zero():
    result = build_history_comparison(
        record(potential_10=0.31, potential_at_10=0.32, overpotential_10=320, tafel_slope=45),
        record("new", potential_at_10=0.33, overpotential_at_10=330, tafel_slope=None),
    )
    metrics = by_key(result)
    assert len(metrics) == 3
    assert metrics["potential_at_10"]["left"] == 0.32
    assert metrics["potential_at_10"]["delta"] == pytest.approx(0.01)
    assert metrics["potential_at_10"]["unit"] == "V"
    assert metrics["overpotential_at_10"]["unit"] == "mV"
    assert metrics["overpotential_at_10"]["delta"] == 10
    assert metrics["tafel_slope"]["delta"] is None
    assert metrics["tafel_slope"]["status"] == "missing"


def test_zero_negative_nonfinite_and_boolean_values_have_honest_deltas():
    result = build_history_comparison(
        record(tafel_slope=0, potential_10=-0.3, overpotential_10=float("nan"), enabled=True),
        record("new", tafel_slope=10, potential_10=-0.2, overpotential_10=float("inf"), enabled=False),
    )
    metrics = by_key(result)
    assert "enabled" not in metrics
    assert metrics["tafel_slope"]["delta"] == 10
    assert metrics["tafel_slope"]["relative_change_percent"] is None
    assert metrics["potential_at_10"]["relative_change_percent"] == pytest.approx(100 / 3)
    assert metrics["overpotential_at_10"]["left"] is None
    json.dumps(result, allow_nan=False)


def test_metric_units_are_module_specific_and_explicit_units_never_subtracted():
    eis = by_key(build_history_comparison(record(data_type="EIS", Cdl=1), record("new", "EIS", Cdl=2)))
    ecsa = by_key(build_history_comparison(record(data_type="ECSA", Cdl=1), record("new", "ECSA", Cdl=2)))
    assert eis["Cdl"]["unit"] == "F"
    assert ecsa["Cdl"]["unit"] == "mF/cm²"
    result = build_history_comparison(
        record(data_type="ECSA", Cs_input=40, Cs_unit="µF/cm²"),
        record("new", "ECSA", Cs_input=0.04, Cs_unit="mF/cm²"),
    )
    assert by_key(result)["Cs_input"]["delta"] is None
    assert by_key(result)["Cs_input"]["status"] == "unit_mismatch"
    assert any("单位不同" in warning for warning in result["warnings"])


def test_parameter_diff_excludes_generated_paths_and_secrets_but_keeps_actual_changes():
    left = {
        "app_version": "6.0.20", "formula_schema_version": "1",
        "params": {"area": 1, "output_dir": "old", "_internal": 1, "api_key": "private-old",
                   "method": {"reference": "RHE", "token": "private-old"}},
    }
    right = {
        "app_version": "6.1.0", "formula_schema_version": "2",
        "params": {"area": 2, "output_dir": "new", "_internal": 2, "api_key": "private-new",
                   "method": {"reference": "RHE", "token": "private-new"}},
    }
    result = build_history_comparison(record(tafel_slope=40), record("new", tafel_slope=41), left_recipe=left, right_recipe=right)
    assert result["parameters_known"]
    assert result["parameter_changes"] == [{"key": "area", "before": 1, "after": 2, "before_present": True, "after_present": True}]
    assert "private" not in json.dumps(result)
    assert len(result["warnings"]) == 2


def test_missing_recipe_does_not_claim_unchanged_parameters():
    result = build_history_comparison(record(tafel_slope=40), record("new", tafel_slope=40), left_recipe={"params": {"area": 1}})
    assert not result["parameters_known"]
    assert not result["parameter_changes"]
    assert any("未保留完整参数" in warning for warning in result["warnings"])


def test_different_project_and_different_types_are_not_comparable():
    with pytest.raises(ValueError, match="相同数据类型"):
        build_history_comparison(record(), record("new", "ECSA"))
    right = record("new")
    right["project_id"] = "another"
    with pytest.raises(ValueError, match="同一项目"):
        build_history_comparison(record(), right)


def test_quality_and_method_changes_are_preserved():
    left, right = record(data_type="EIS", circuit_model="RC", Rs=1), record("new", "EIS", circuit_model="CPE", Rs=2)
    left["quality_summary"] = {"warnings": 0}
    right["quality_summary"] = {"warnings": 1}
    result = build_history_comparison(left, right)
    assert result["quality"]["changed"]
    assert result["method_changes"][0]["key"] == "circuit_model"
    assert any("模型" in warning for warning in result["warnings"])


def test_source_comparison_checks_the_selected_records_auxiliary_inputs():
    left = {"params": {}, "inputs": [
        {"path": "sample.txt", "role": "primary", "sha256": "same"},
        {"path": "eis.txt", "role": "ir_eis", "sha256": "old", "for_paths": ["sample.txt"]},
        {"path": "unrelated.txt", "role": "primary", "sha256": "ignored"},
    ]}
    right = {"params": {}, "inputs": [
        {"path": "sample.txt", "role": "primary", "sha256": "same"},
        {"path": "eis.txt", "role": "ir_eis", "sha256": "new", "for_paths": ["sample.txt"]},
    ]}
    result = build_history_comparison(record(tafel_slope=40), record("new", tafel_slope=41), left_recipe=left, right_recipe=right)
    assert result["sources"]["state"] == "changed"
    assert len(result["sources"]["left"]) == 2
    assert any("辅助输入指纹不同" in warning for warning in result["warnings"])


@pytest.mark.parametrize("left,right", [(None, "a"), ("", "b"), ("a", "a"), ([], "a")])
def test_invalid_record_selection_returns_actionable_error(left, right):
    assert compare_history_records(left_record_key=left, right_record_key=right)["status"] == "error"


def test_api_reads_exact_versions_even_when_a_newer_record_has_same_name(tmp_path, monkeypatch):
    from electrochem_v6.core import history_compare
    from electrochem_v6.store import run_recipes
    from electrochem_v6.store.database import Database

    db = Database(str(tmp_path / "compare.db"))
    monkeypatch.setattr(history_compare, "get_database", lambda: db)
    monkeypatch.setattr(run_recipes, "get_run_recipe", lambda _key: {"params": {"area": 1}})
    try:
        for run, value in (("old", 10), ("middle", 20), ("newest", 999)):
            db.add_history_record({**record(run, tafel_slope=value), "timestamp": "2026-09-07 10:00:00"})
        records = {item["run_id"]: item for item in db.get_all_history_records()}
        result = compare_history_records(
            left_record_key=records["old"]["record_key"], right_record_key=records["middle"]["record_key"], project_id="project",
        )
        assert result["status"] == "success"
        assert by_key(result["comparison"])["tafel_slope"]["delta"] == 10
        assert result["comparison"]["right"]["run_id"] == "middle"
        assert compare_history_records(left_record_key=records["old"]["record_key"], right_record_key="deleted")["status"] == "error"
        assert compare_history_records(left_record_key=records["old"]["record_key"], right_record_key=records["middle"]["record_key"], project_id="other")["status"] == "error"
    finally:
        db.close_all()
