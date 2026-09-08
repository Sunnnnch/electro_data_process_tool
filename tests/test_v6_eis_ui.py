"""Real EIS controls, templates, processing and exact-record replay contracts."""

from pathlib import Path

import numpy as np
import pytest

from electrochem_v6.core.process_service import _build_gui_vars, _validate_payload
from electrochem_v6.core.processing_registry import processing_parameter_schema
from electrochem_v6.store.run_recipes import get_run_recipe
from electrochem_v6.store.runtime import get_database
from test_v6_project_recovery_ui import recovery_browser as recovery_browser

MODELS = [
    "randles_rc", "randles_cpe", "randles_warburg_rc", "randles_warburg_cpe",
    "two_time_constants_rc", "two_time_constants_cpe",
]


@pytest.mark.parametrize("lower,upper,valid", [
    (None, None, True), ("", "", True), (1, None, True), (None, 1000, True),
    (1, 1, True), (0, 1, False), (False, None, False), (True, None, False),
    (-1, 10, False), (100, 1, False), (float("inf"), None, False),
    (None, float("nan"), False), ("invalid", 1, False),
])
def test_eis_frequency_schema_validation_and_nullable_coercion(lower, upper, valid):
    payload = {"params": {"eis_fit_frequency_min_hz": lower, "eis_fit_frequency_max_hz": upper}}
    error = _validate_payload(payload, ["EIS"])
    assert (error is None) is valid, error
    if valid:
        effective = _build_gui_vars(["EIS"], payload)
        assert effective["eis_fit_frequency_min_hz"] == (None if lower in (None, "") else lower)
        assert effective["eis_fit_frequency_max_hz"] == (None if upper in (None, "") else upper)


def _open_eis(page, manager, payload, source, *, two_time_constants=False):
    folder = source.parent / "eis"
    folder.mkdir()
    data = folder / "EIS_demo.txt"
    frequency = np.logspace(-1, 5, 73)
    impedance = 4 + 90 / (1 + 1j * 2 * np.pi * frequency * 90 * 3e-5)
    if two_time_constants:
        frequency = np.logspace(-2, 6, 97)
        impedance = 4 + 25 / (1 + 1j * 2 * np.pi * frequency * 25 * 4e-6) + 100 / (1 + 1j * 2 * np.pi * frequency * 100 * 1e-3)
    np.savetxt(data, np.column_stack([frequency, impedance.real, impedance.imag]), delimiter="\t")
    page.route("**/api/v1/system/select-folder", lambda route: route.fulfill(
        json={"status": "success", "folder_path": str(folder)}))
    page.goto(f"http://127.0.0.1:{manager.port}/ui", wait_until="networkidle")
    page.locator('.proc-type-check[value="EIS"]').check()
    page.locator('.proc-type-check[value="LSV"]').uncheck()
    page.select_option("#proc-project", label=payload["project_name"])
    page.fill("#pro-offset", "0")
    page.click("#proc-data-pick")
    page.click("#proc-pick-folder")
    page.wait_for_selector(".source-file-item")
    assert page.locator(".source-file-item").count() == 1
    return data


def _advanced(page):
    details = page.locator("#pro-eis-analysis-advanced")
    if not details.evaluate("el => el.open"):
        details.locator("summary").click()


def test_eis_six_models_schema_templates_and_independent_kk_controls(recovery_browser):
    page, manager, payload, source, _errors = recovery_browser
    _open_eis(page, manager, payload, source)
    response = page.request.get(f"http://127.0.0.1:{manager.port}/api/v1/process/schema?data_types=EIS")
    assert response.ok
    schema = response.json()["schema"]
    assert schema == processing_parameter_schema(["EIS"])
    parameters = {item["key"]: item for item in schema["parameters"]}
    assert parameters["eis_circuit_model"]["options"] == MODELS
    assert parameters["eis_fit_weighting"]["options"] == ["uniform", "modulus"]
    assert parameters["eis_fit_frequency_min_hz"]["default"] is None
    assert parameters["eis_fit_frequency_max_hz"]["default"] is None
    assert parameters["eis_fit_min_r2"]["default"] == 0.5
    assert parameters["plot_eis_residuals"]["default"] is True
    assert page.locator("#pro-eis-circuit-model option").evaluate_all("els => els.map(el => el.value)") == MODELS
    assert not page.locator("#pro-eis-analysis-advanced").evaluate("el => el.open")
    _advanced(page)
    assert page.locator("#pro-eis-residual-options").is_hidden()
    page.check("#pro-eis-kk-check")
    assert page.locator("#pro-eis-residual-options").is_visible()
    assert not page.locator("#pro-eis-randles-fit").is_checked()
    for model in MODELS:
        page.select_option("#pro-eis-circuit-model", model)
        assert page.locator(f'[data-eis-model-hint="{model}"]').is_visible()
        assert page.locator("[data-eis-model-hint]:visible").count() == 1
        assert page.evaluate("collectProcessPayload().params.eis_circuit_model") == model
    page.fill("#pro-eis-fit-frequency-min-hz", "10")
    page.fill("#pro-eis-fit-frequency-max-hz", "10000")
    page.select_option("#pro-eis-fit-weighting", "modulus")
    page.uncheck("#pro-eis-plot-residuals")
    page.locator("#process-step-template > summary").click()
    page.fill("#tmpl-name", "EIS exact analysis options")
    with page.expect_response(lambda r: r.url.endswith("/process/templates") and r.request.method == "POST") as saved:
        page.click("#tmpl-save")
    assert saved.value.ok
    stored = saved.value.request.post_data_json["state"]
    assert stored["values"]["pro-eis-fit-frequency-min-hz"] == "10"
    assert stored["values"]["pro-eis-fit-weighting"] == "modulus"
    assert stored["checks"]["pro-eis-kk-check"] is True
    assert stored["checks"]["pro-eis-plot-residuals"] is False
    page.fill("#pro-eis-fit-frequency-min-hz", "1")
    page.uncheck("#pro-eis-kk-check")
    page.select_option("#pro-eis-circuit-model", "randles_rc")
    page.wait_for_function("() => [...document.querySelector('#tmpl-select').options].some(o => o.value === 'EIS exact analysis options')")
    page.select_option("#tmpl-select", "EIS exact analysis options")
    page.click("#tmpl-load")
    restored = page.evaluate("collectProcessPayload().params")
    assert restored["eis_circuit_model"] == "two_time_constants_cpe"
    assert restored["eis_fit_frequency_min_hz"] == 10
    assert restored["eis_fit_frequency_max_hz"] == 10000
    assert restored["eis_fit_weighting"] == "modulus"
    assert restored["eis_kk_check"] is True and restored["eis_randles_fit"] is False
    assert restored["plot_eis_residuals"] is False
    assert page.locator('[data-eis-model-hint="two_time_constants_cpe"]').is_visible()
    assert page.locator("#pro-eis-residual-options").is_visible()
    page.fill("#pro-eis-fit-frequency-min-hz", "0")
    error = page.evaluate("() => {try {collectProcessPayload(); return '';} catch (e) {return e.message;}}")
    assert "0" in error and "Hz" in error
    page.fill("#pro-eis-fit-frequency-min-hz", "20000")
    assert "最低频率" in page.evaluate("() => {try {collectProcessPayload(); return '';} catch (e) {return e.message;}}")
    page.fill("#pro-eis-fit-frequency-min-hz", "")
    page.fill("#pro-eis-fit-frequency-max-hz", "")
    assert page.evaluate("collectProcessPayload().params.eis_fit_frequency_min_hz") is None
    page.select_option("#lang-select", "en")
    page.set_viewport_size({"width": 600, "height": 1100})
    assert page.locator("[data-eis-model-hint]:visible").inner_text().startswith("Two non-ideal")
    assert page.evaluate("() => document.documentElement.scrollWidth <= innerWidth + 1")


def test_eis_real_fit_and_kk_run_replays_cleared_frequency_bounds(recovery_browser):
    page, manager, payload, source, _errors = recovery_browser
    _open_eis(page, manager, payload, source, two_time_constants=True)
    page.select_option("#pro-eis-circuit-model", "two_time_constants_rc")
    page.check("#pro-eis-randles-fit")
    page.check("#pro-eis-kk-check")
    _advanced(page)
    page.fill("#pro-eis-fit-frequency-min-hz", "1")
    page.fill("#pro-eis-fit-frequency-max-hz", "10000")
    page.select_option("#pro-eis-fit-weighting", "modulus")
    with page.expect_response("**/process/preflight") as preflight:
        page.click("#proc-preflight-btn")
    assert preflight.value.ok, preflight.value.text()
    page.wait_for_function("() => latestPreflightScan !== null")
    page.select_option("#pro-eis-fit-weighting", "uniform")
    assert page.evaluate("latestPreflightScan") is None
    page.select_option("#pro-eis-fit-weighting", "modulus")
    with page.expect_response("**/process/preflight"):
        page.click("#proc-preflight-btn")
    page.wait_for_function("() => latestPreflightScan !== null")
    with page.expect_response(lambda r: r.url.endswith("/process/jobs") and r.request.method == "POST") as submitted:
        page.click("#proc-run")
    assert submitted.value.status == 202
    page.wait_for_function("() => latestProcessResult?.manifest?.run?.run_id && processRunState === 'complete'", timeout=90000)
    result = page.evaluate("latestProcessResult")
    run_id = result["manifest"]["run"]["run_id"]
    original = get_run_recipe(run_id)
    assert original["status"] == "succeeded" and len(original["record_keys"]) == 1
    assert original["params"]["eis_fit_frequency_min_hz"] == 1
    assert original["params"]["eis_fit_frequency_max_hz"] == 10000
    assert original["params"]["eis_fit_weighting"] == "modulus"
    assert original["params"]["eis_kk_check"] is True
    outputs = list(Path(original["output_dir"]).rglob("*"))
    assert any("residual" in path.name.lower() and path.suffix == ".png" for path in outputs)
    page.click("#tab-btn-project")
    page.locator(f'[data-project-id="{payload["project_id"]}"]').click()
    page.wait_for_selector(".project-result-row")
    page.locator(".project-record-open").first.click()
    page.wait_for_selector(".project-eis-analysis")
    metrics = page.locator(".project-result-metrics").inner_text()
    assert "R2: 100 Ohm" in metrics, metrics
    assert "R1: 25 Ohm" in metrics, metrics
    assert "R²: 100" not in metrics, metrics
    assert "R²: 1" in metrics, metrics
    assert "KK" in page.locator(".project-eis-analysis").inner_text()
    assert "Hz" in page.locator(".project-eis-analysis").inner_text()
    assert "证明所选电路正确" in page.locator(".project-eis-analysis").inner_text()
    page.locator(".project-eis-analysis details summary").click()
    assert "95%" in page.locator(".project-eis-analysis").inner_text()
    with page.expect_response("**/replay-plan"):
        page.click("#project-replay-btn")
    page.select_option("#project-replay-mode", "modified")
    page.locator(".project-replay-more > summary").click()
    def field(key):
        return page.locator(f'.project-replay-parameter[data-param-key="{key}"]')
    assert field("eis_circuit_model").locator("option").count() == 6
    assert "双时间常数" in field("eis_circuit_model").locator("option:checked").inner_text()
    assert field("eis_fit_frequency_min_hz").input_value() == "1"
    field("eis_fit_frequency_min_hz").fill("")
    field("eis_fit_frequency_max_hz").fill("")
    field("eis_fit_weighting").select_option("uniform")
    field("eis_randles_fit").uncheck()
    assert field("eis_kk_check").is_checked()
    assert page.locator("#project-replay-execute").is_disabled()
    with page.expect_response("**/replay-plan") as replay_plan:
        page.click("#project-replay-check")
    plan = replay_plan.value.json()["plan"]
    assert plan["can_replay"], plan
    sent = replay_plan.value.request.post_data_json["params"]
    assert sent["eis_fit_frequency_min_hz"] is None and sent["eis_fit_frequency_max_hz"] is None
    assert sent["eis_randles_fit"] is False and sent["eis_fit_weighting"] == "uniform"
    with page.expect_response("**/replay") as replayed:
        page.click("#project-replay-execute")
    assert replayed.value.status == 202
    page.wait_for_function("() => document.querySelector('#project-replay-status').textContent.includes('复算完成')", timeout=90000)
    job = get_database().get_processing_job(replayed.value.json()["job_id"])
    assert job["status"] == "succeeded", job
    new_id = job["result"]["result"]["manifest"]["run"]["run_id"]
    new_recipe = get_run_recipe(new_id)
    assert new_recipe["parent_run_id"] == run_id
    assert new_recipe["output_dir"] != original["output_dir"]
    assert new_recipe["params"]["eis_fit_frequency_min_hz"] is None
    assert new_recipe["params"]["eis_fit_frequency_max_hz"] is None
    assert new_recipe["params"]["eis_kk_check"] is True
    assert new_recipe["params"]["eis_randles_fit"] is False
    assert get_run_recipe(run_id)["params"]["eis_fit_frequency_min_hz"] == 1
