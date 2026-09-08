"""Replicate statistics count experiments, never rerun versions or deleted data."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from urllib.parse import quote
from urllib.request import urlopen

import pytest

from electrochem_v6.core.replicate_service import (
    export_replicates_csv,
    get_replicates,
    list_replicates,
    preview_replicates,
    replicate_metric_svg,
    save_replicates,
)
from electrochem_v6.store.projects import create_project
from electrochem_v6.store.replicate_groups import cleanup_project_replicates, mark_deleted_replicate_records
from electrochem_v6.store.run_recipes import get_run_recipe, save_run_recipe
from electrochem_v6.store.runtime import get_database, reset_runtime
from test_v6_project_templates import _http, isolated_runtime  # noqa: F401


@pytest.fixture
def project(request):
    request.getfixturevalue("isolated_runtime")
    return create_project("重复实验统计验收")["project"]["id"]


def seed(project, name, value=1.0, *, data_type="LSV", run=None, sha=None, recipe=True, parent_run=None,
         parent_record=None, results=None, path=None, params=None, eis_analysis=None):
    from electrochem_v6.core.process_service import _build_gui_vars
    run = run or "run-" + name
    path = path or "D:/experiments/" + name + ".txt"
    record = {"project_id": project, "sample_name": name, "file_name": name + ".txt", "file_path": path,
              "timestamp": "2026-09-07 12:00:00", "type": data_type, "run_id": run,
              "results": results if results is not None else {"tafel_slope": value}}
    if eis_analysis is not None:
        record["eis_analysis"] = eis_analysis
    get_database().add_history_record(record)
    key = get_database()._history_record_key(record)
    assert get_database().get_history_record(key)
    if recipe:
        existing = get_run_recipe(run) or {}
        save_run_recipe({"run_id": run, "project_id": project, "status": "succeeded", "params": _build_gui_vars([data_type], {"params": params or {}}),
                         "inputs": [*(existing.get("inputs") or []), {"path": path, "role": "primary", "data_type": data_type,
                                    "sha256": sha if sha is not None else hashlib.sha256(name.encode()).hexdigest()}],
                         "records": [*(existing.get("records") or []), {"record_key": key, "input_paths": [path]}],
                         "parent_run_id": parent_run, "parent_record_key": parent_record})
    return key


def draft(keys, **changes):
    return {"name": "催化剂独立重复", "record_keys": keys, "exclusions": [], "independence_confirmed_keys": [], **changes}


def metric(group, key="tafel_slope"):
    return next(item for item in group["metrics"] if item["key"] == key)


def test_eis_weight_and_frequency_window_changes_require_comparability_review(project):
    one = seed(project, "uniform", data_type="EIS", results={"Rs": 10}, params={"eis_fit_weighting": "uniform"})
    two = seed(project, "modulus", data_type="EIS", results={"Rs": 12},
               params={"eis_fit_weighting": "modulus", "eis_fit_frequency_min_hz": 100})
    result = preview_replicates(project, draft([one, two]))
    assert not result["can_save"]
    assert metric(result, "Rs")["n"] == 0
    assert any("计算口径" in issue for issue in result["issues"])


@pytest.mark.parametrize("second_n", [.9, None])
def test_double_cpe_q_is_not_pooled_when_exponents_differ_or_are_unknown(project, second_n):
    one = seed(project, "branch-one", data_type="EIS", results={"Q1": .001, "n1": .8, "R1": 10})
    two = seed(project, "branch-two", data_type="EIS", results={"Q1": .002, "n1": second_n, "R1": 12})
    result = preview_replicates(project, draft([one, two]))
    assert metric(result, "Q1")["status"] == "unit_mismatch"
    assert metric(result, "Q1")["mean"] is None and metric(result, "Q1")["n"] == 0
    assert metric(result, "R1")["mean"] == 11


def test_eis_fit_review_survives_replicate_statistics_and_exclusion(project):
    one = seed(project, "ambiguous", data_type="EIS", results={"R1": 10}, eis_analysis={
        "fit": {"accepted": True, "status": "needs_review", "review_required": True,
                "review_reasons": ["branches_indistinguishable"]},
        "kk": {"status": "review", "reason": "large KK residual"}})
    two = seed(project, "resolved", data_type="EIS", results={"R1": 12})
    result = preview_replicates(project, draft([one, two]))
    assert metric(result, "R1")["mean"] == 11
    assert any("branches_indistinguishable" in warning for warning in result["warnings"])
    assert any("large KK residual" in warning for warning in result["warnings"])
    excluded = preview_replicates(project, draft([one, two], exclusions=[{"record_key": one, "reason": "支路无法可靠区分"}]))
    assert metric(excluded, "R1")["mean"] == 12
    assert not any("branches_indistinguishable" in warning for warning in excluded["warnings"])
    assert excluded["members"][0]["analysis_warnings"]


def test_zero_missing_exclusions_sample_sd_and_durable_reload(project):
    keys = [seed(project, "zero", 0), seed(project, "two", 2), seed(project, "missing", None), seed(project, "outlier", 999)]
    group = save_replicates(project, draft(keys, exclusions=[{"record_key": keys[-1], "reason": "电极接触不良，依据实验记录排除"}]))
    value = metric(group)
    assert value["n"] == 2
    assert value["missing_n"] == 1
    assert value["mean"] == 1
    assert value["sample_sd"] == pytest.approx(math.sqrt(2))
    assert [point["value"] for point in value["points"]] == [0, 2, None, 999]
    reset_runtime()
    reopened = get_replicates(group["group_id"])
    assert metric(reopened) == value
    assert reopened["exclusions"] == group["exclusions"]
    assert list_replicates(project)[0]["group_id"] == group["group_id"]


@pytest.mark.parametrize("values,count,mean", [([4], 1, 4), ([None], 0, None)])
def test_n_one_and_n_zero_never_claim_zero_uncertainty(project, values, count, mean):
    group = save_replicates(project, draft([seed(project, str(index), value) for index, value in enumerate(values)]))
    value = metric(group)
    assert value["n"] == count
    assert value["mean"] == mean
    assert value["sample_sd"] is None
    if count:
        assert "undefined (n=1)" in replicate_metric_svg(group, "tafel_slope")
    else:
        with pytest.raises(ValueError, match="不能生成误差条"):
            replicate_metric_svg(group, "tafel_slope")


def test_same_hash_or_replay_lineage_cannot_inflate_n_even_with_confirmation(project):
    first = seed(project, "old", 10)
    copied = seed(project, "copied", 20, sha=hashlib.sha256(b"old").hexdigest())
    changed_version = seed(project, "changed-renamed", 30, parent_run="run-old", parent_record=first)
    for second in (copied, changed_version):
        payload = draft([first, second], independence_confirmed_keys=[first, second])
        preview = preview_replicates(project, payload)
        assert not preview["can_save"]
        assert preview["source_conflicts"] == [[first, second]]
        assert metric(preview)["n"] == 0
        with pytest.raises(ValueError, match="版本"):
            save_replicates(project, payload)
        chosen = save_replicates(project, {**payload, "exclusions": [{"record_key": first, "reason": "使用复核后的版本"}]})
        assert metric(chosen)["n"] == 1
        assert metric(chosen)["mean"] in (20, 30)


def test_distinct_files_in_same_batch_are_independent_but_replay_cannot_duplicate_a_slot(project):
    one = seed(project, "batch-one", 10, run="batch")
    two = seed(project, "batch-two", 20, run="batch")
    assert metric(save_replicates(project, draft([one, two])))["n"] == 2
    replay = seed(project, "batch-one", 100, run="replayed", parent_run="batch", sha=hashlib.sha256(b"changed-data").hexdigest())
    assert not preview_replicates(project, draft([one, replay]))["can_save"]
    assert metric(save_replicates(project, draft([two, replay])))["n"] == 2


def test_ambiguous_parent_mapping_blocks_replay_as_new_experiment(project):
    one = seed(project, "first", 1)
    replay = seed(project, "renamed", 2, parent_run="run-first")
    preview = preview_replicates(project, draft([one, replay], independence_confirmed_keys=[replay]))
    assert not preview["can_save"]
    assert preview["source_conflicts"]


def test_missing_source_evidence_needs_member_specific_confirmation_not_inherited(project):
    first = seed(project, "legacy-one", 1, recipe=False)
    second = seed(project, "legacy-two", 3, recipe=False)
    preview = preview_replicates(project, draft([first, second], independence_confirmed_keys=[first]))
    assert not preview["can_save"]
    with pytest.raises(ValueError, match="来源证据"):
        save_replicates(project, draft([first, second]))
    payload = draft([first, second], independence_confirmed_keys=[first, second])
    payload["analysis_conditions_confirmation"] = preview_replicates(project, payload)["analysis_conditions"]["signature"]
    group = save_replicates(project, payload)
    assert metric(group)["n"] == 2
    third = seed(project, "legacy-three", 9, recipe=False)
    with pytest.raises(ValueError, match="当前组内"):
        save_replicates(project, draft([first, third], independence_confirmed_keys=[first, second], revision=group["revision"]), group_id=group["group_id"])
    with pytest.raises(ValueError, match="来源证据"):
        save_replicates(project, draft([first, third], independence_confirmed_keys=[first], revision=group["revision"]), group_id=group["group_id"])


def test_unit_mismatch_cpe_dimensions_unknown_units_and_other_valid_metrics_are_separate(project):
    one = seed(project, "eis-one", data_type="EIS", results={"Rs": 1, "Rct": {"value": 1, "unit": "Ω"}, "CPE_Q": 0.01, "CPE_n": .8, "mystery": 7})
    two = seed(project, "eis-two", data_type="EIS", results={"Rs": 3, "Rct": {"value": 2, "unit": "kΩ"}, "CPE_Q": 0.03, "CPE_n": .9, "mystery": 8})
    group = save_replicates(project, draft([one, two]))
    assert metric(group, "Rs")["mean"] == 2
    for key in ("Rct", "CPE_Q"):
        assert metric(group, key)["status"] == "unit_mismatch"
        assert metric(group, key)["n"] == 0
        assert metric(group, key)["mean"] is None
        assert metric(group, key)["measured_n"] == 2
    assert metric(group, "mystery")["status"] == "unit_unknown"
    assert metric(group, "CPE_n")["n"] == 2


def test_deleted_record_is_tombstoned_and_reimport_does_not_restore_it(project):
    one, two = seed(project, "one", 1), seed(project, "two", 3)
    group = save_replicates(project, draft([one, two]))
    with get_database().transaction() as connection:
        mark_deleted_replicate_records(connection, [one])
        connection.execute("DELETE FROM history_records WHERE record_key=?", (one,))
    deleted = get_replicates(group["group_id"])
    assert deleted["members"][0]["status"] == "deleted"
    assert metric(deleted)["n"] == 1
    assert seed(project, "one", 999) == one
    assert metric(get_replicates(group["group_id"]))["mean"] == 3
    assert get_replicates(group["group_id"])["deleted_record_keys"] == [one]


def test_deletion_hooks_and_stale_revisions_do_not_overwrite_changes(project):
    one = seed(project, "one", 1)
    group = save_replicates(project, draft([one]))
    updated = save_replicates(project, draft([one], name="已编辑", revision=group["revision"]), group_id=group["group_id"])
    assert updated["revision"] == group["revision"] + 1
    with pytest.raises(ValueError, match="其他操作"):
        save_replicates(project, draft([one], revision=group["revision"]), group_id=group["group_id"])
    with get_database().transaction() as connection:
        assert cleanup_project_replicates(connection, project) == 1
        connection.execute("DELETE FROM projects WHERE id=?", (project,))
    with pytest.raises(LookupError):
        get_replicates(group["group_id"])


def test_cross_project_type_empty_or_bad_exclusion_cannot_be_saved(project):
    one = seed(project, "one")
    other_project = create_project("另一个项目")["project"]["id"]
    foreign = seed(other_project, "foreign")
    cv = seed(project, "cv", data_type="CV", results={"charge_mC": 2})
    for payload in [draft([one, foreign]), draft([one, cv]), draft([one, one]), draft([]),
                    draft([one], exclusions=[{"record_key": one, "reason": ""}]), draft([one], independence_confirmed_keys=True)]:
        with pytest.raises(ValueError):
            save_replicates(project, payload)
    assert list_replicates(project) == []


def test_exports_include_exact_points_reasons_source_hashes_and_sample_sd(project):
    one, two, excluded = seed(project, "=untrusted", 0), seed(project, "two", 4), seed(project, "excluded", 99)
    group = save_replicates(project, draft([one, two, excluded], name="<script>invalid</script>",
                                        exclusions=[{"record_key": excluded, "reason": "@bad electrode"}]))
    rows = list(csv.DictReader(io.StringIO(export_replicates_csv(group).decode("utf-8-sig"))))
    assert [float(row["value"]) for row in rows] == [0, 4, 99]
    assert rows[0]["sample"] == "'=untrusted"
    assert rows[2]["exclusion_reason"] == "'@bad electrode"
    assert rows[2]["included"] == "False"
    assert all(row["valid_n"] == "2" and len(row["source_sha256"]) == 64 for row in rows)
    svg = replicate_metric_svg(group, "tafel_slope")
    assert "<script>" not in svg and "&lt;script&gt;" in svg
    assert "ddof=1" in svg and "sample SD" in svg
    json.dumps(group, allow_nan=False)


def test_real_routes_persist_reload_validate_and_download(project):
    from electrochem_v6.server import V6ServerManager
    from test_v6_ui_playwright import _get_free_port

    keys = [seed(project, "one", 0), seed(project, "two", 2)]
    manager = V6ServerManager(port=_get_free_port())
    assert manager.start()[0]
    base = f"http://127.0.0.1:{manager.port}/api/v1"
    try:
        code, preview = _http(f"{base}/projects/{project}/replicate-preview", draft(keys))
        assert code == 200 and preview["group"]["can_save"]
        code, created = _http(f"{base}/projects/{project}/replicate-groups", draft(keys))
        assert code == 200
        group = created["group"]
        url = f"{base}/replicate-groups/{group['group_id']}"
        assert _http(url)[1]["group"]["record_keys"] == keys
        assert _http(f"{base}/projects/{project}/replicate-groups")[1]["groups"][0]["name"] == group["name"]
        for export_format in ("csv", "svg"):
            with urlopen(f"{url}/export?format={export_format}&metric={quote('tafel_slope')}", timeout=5) as response:
                body = response.read()
                assert response.status == 200 and b"sample" in body
                assert "attachment" in response.headers["Content-Disposition"]
        assert _http(url + "/update", draft(keys, revision=group["revision"], name="改名"))[0] == 200
        assert _http(url + "/update", draft(keys, revision=group["revision"]))[0] == 400
        assert _http(url + "/delete", {})[0] == 200
        assert _http(url)[0] == 404
    finally:
        manager.stop()


def test_two_database_instances_cannot_both_save_the_same_revision(project, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, local

    from electrochem_v6.store import replicate_groups
    from electrochem_v6.store.database import Database

    one = seed(project, "one", 1)
    group = save_replicates(project, draft([one]))
    with get_database().read() as connection:
        db_path = connection.execute("PRAGMA database_list").fetchone()[2]
    databases = [Database(db_path), Database(db_path)]
    thread_state = local()
    first_validated, release_first, second_started = Event(), Event(), Event()
    real_dump = replicate_groups._dump

    def held_dump(value):
        if thread_state.index == 0:
            first_validated.set()
            assert release_first.wait(5)
        return real_dump(value)

    monkeypatch.setattr(replicate_groups, "get_database", lambda: databases[thread_state.index])
    monkeypatch.setattr(replicate_groups, "_dump", held_dump)

    def update(index):
        thread_state.index = index
        if index:
            with databases[index].read() as connection:
                connection.set_trace_callback(lambda sql: second_started.set() if sql == "BEGIN IMMEDIATE" else None)
        try:
            return replicate_groups.save_replicate_group({**group, "name": f"writer-{index}"}, expected_revision=group["revision"])
        except ValueError as exc:
            return str(exc)

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            first = workers.submit(update, 0)
            assert first_validated.wait(5)
            second = workers.submit(update, 1)
            assert second_started.wait(5)
            release_first.set()
            assert first.result(5)["name"] == "writer-0"
            assert "其他操作修改" in second.result(5)
    finally:
        release_first.set()
        for database in databases:
            database.close_all()


def test_actual_cv_batch_provenance_counts_distinct_inputs_but_not_reprocessing(project, tmp_path):
    from conftest import _write_tsv, make_cv_rows
    from electrochem_v6.core.process_service import process_folder

    folder = tmp_path / "actual-inputs"
    folder.mkdir()
    one = _write_tsv(folder / "CV_one.txt", make_cv_rows(n_half=20))
    two = _write_tsv(folder / "CV_two.txt", make_cv_rows(n_half=22))
    payload = {"project_id": project, "project_name": "重复实验统计验收", "folder_path": str(folder),
               "input_files": [{"path": str(one), "data_type": "CV"}, {"path": str(two), "data_type": "CV"}],
               "data_types": ["CV"], "params": {"area": 1, "potential_offset": 0}}
    first = process_folder(payload)
    assert first["status"] == "success", first
    run = first["result"]["manifest"]["run"]["run_id"]
    originals = [record for record in get_database().get_all_history_records() if record["run_id"] == run]
    assert len(originals) == 2
    group = save_replicates(project, draft([record["record_key"] for record in originals]))
    assert metric(group, "data_points")["n"] == 2
    assert all(member["source"]["state"] == "verified" for member in group["members"])
    original_one = next(record for record in originals if record["file_path"] == str(one))
    second = process_folder({**payload, "input_files": [{"path": str(one), "data_type": "CV"}],
                             "params": {"area": 2, "potential_offset": 0},
                             "_parent_run_id": run, "_parent_record_key": original_one["record_key"]})
    assert second["status"] == "success", second
    new_run = second["result"]["manifest"]["run"]["run_id"]
    new_record = next(record for record in get_database().get_all_history_records() if record["run_id"] == new_run)
    preview = preview_replicates(project, draft([original_one["record_key"], new_record["record_key"]]))
    assert not preview["can_save"] and preview["source_conflicts"]


def test_partial_input_coverage_requires_explicit_source_confirmation(project):
    key = seed(project, "partial", 1)
    recipe = get_run_recipe("run-partial")
    recipe["records"][0]["input_paths"].append("D:/experiments/missing-second-input.txt")
    save_run_recipe(recipe)
    group = preview_replicates(project, draft([key]))
    assert group["members"][0]["source"]["state"] == "unverified"
    assert group["members"][0]["source"]["missing_input_paths"]
    assert not group["can_save"]


def test_deleted_common_parent_still_blocks_changed_versions(project):
    one = seed(project, "same-path", 1, run="child-a", sha="a" * 64, parent_run="missing-parent")
    two = seed(project, "same-path", 2, run="child-b", sha="b" * 64, parent_run="missing-parent")
    group = preview_replicates(project, draft([one, two], independence_confirmed_keys=[one, two]))
    assert "missing-parent" in group["members"][0]["source"]["ancestor_run_ids"]
    assert not group["can_save"] and group["source_conflicts"]
    assert metric(group)["n"] == 0


def test_calculation_conventions_require_fresh_specific_confirmation(project):
    first = seed(project, "manual", results={"potential_at_10": .1}, params={"potential_mode": "manual", "potential_offset": 0})
    second = seed(project, "rhe", results={"potential_at_10": .2}, params={"potential_mode": "formula_rhe", "rhe_ph": 14,
                  "rhe_temperature_c": 25, "reference_electrode_preset": "agcl_sat_kcl"})
    payload = draft([first, second])
    preview = preview_replicates(project, payload)
    assert preview["analysis_conditions"]["requires_confirmation"]
    assert "potential_mode" in preview["analysis_conditions"]["differences"]
    assert not preview["can_save"]
    assert metric(preview, "potential_at_10")["status"] == "blocked"
    assert metric(preview, "potential_at_10")["n"] == 0
    payload["analysis_conditions_confirmation"] = preview["analysis_conditions"]["signature"]
    saved = save_replicates(project, payload)
    assert metric(saved, "potential_at_10")["n"] == 2
    assert saved["analysis_conditions"]["confirmed"]
    recipe = get_run_recipe("run-rhe")
    recipe["params"]["area"] = 4
    save_run_recipe(recipe)
    reopened = get_replicates(saved["group_id"])
    assert not reopened["analysis_conditions"]["confirmed"]
    assert not reopened["can_save"]
    assert metric(reopened, "potential_at_10")["n"] == 0
    with pytest.raises(ValueError, match="计算口径"):
        save_replicates(project, {**payload, "revision": saved["revision"]}, group_id=saved["group_id"])


def test_empty_measurements_export_member_and_exclusion_audit(project):
    one = seed(project, "empty", results={})
    group = save_replicates(project, draft([one]))
    rows = list(csv.DictReader(io.StringIO(export_replicates_csv(group).decode("utf-8-sig"))))
    assert len(rows) == 1 and rows[0]["record_key"] == one
    assert rows[0]["valid_n"] == "0" and rows[0]["mean"] == ""


@pytest.mark.parametrize("action", ["record", "project", "hard"])
def test_delete_write_lock_prevents_concurrent_group_ghosts(project, monkeypatch, action):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, local

    from electrochem_v6.store import replicate_groups
    from electrochem_v6.store.database import Database

    one, two = seed(project, "one", 1), seed(project, "two", 3)
    group = save_replicates(project, draft([one, two]))
    with get_database().read() as connection:
        db_path = connection.execute("PRAGMA database_list").fetchone()[2]
    databases = [Database(db_path), Database(db_path)]
    thread_state = local()
    deletion_locked, release_delete, save_started = Event(), Event(), Event()
    real_get_database = replicate_groups.get_database
    monkeypatch.setattr(replicate_groups, "get_database", lambda: databases[thread_state.index] if hasattr(thread_state, "index") else real_get_database())

    def delete():
        thread_state.index = 0

        def trace(statement):
            if statement.startswith("SELECT key,value FROM meta") and not deletion_locked.is_set():
                deletion_locked.set()
                assert release_delete.wait(5)

        with databases[0].read() as connection:
            connection.set_trace_callback(trace)
        if action == "record":
            return databases[0].update_history_by_key(one, "delete")
        if action == "hard":
            return databases[0].delete_project(project, hard=True)
        return databases[0].purge_project(project)

    def save():
        thread_state.index = 1
        with databases[1].read() as connection:
            connection.set_trace_callback(lambda statement: save_started.set() if statement == "BEGIN IMMEDIATE" else None)
        try:
            replicate_groups.save_replicate_group({**group, "group_id": "concurrent-new-group"})
        except (ValueError, LookupError) as exc:
            return str(exc)
        return "unexpected success"

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            deleting = workers.submit(delete)
            assert deletion_locked.wait(5)
            saving = workers.submit(save)
            assert save_started.wait(5)
            release_delete.set()
            assert deleting.result(5)
            assert "删除" in saving.result(5)
        assert replicate_groups.get_replicate_group("concurrent-new-group") is None
        if action == "record":
            seed(project, "one", 999)
            reopened = get_replicates(group["group_id"])
            assert reopened["members"][0]["status"] == "deleted"
            assert metric(reopened)["mean"] == 3
        else:
            assert replicate_groups.get_replicate_group(group["group_id"]) is None
    finally:
        release_delete.set()
        for database in databases:
            database.close_all()
