"""Bound read recovery without repeating writes, responses, or cancellations."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_v6_replicate_groups import seed
from test_v6_replicate_groups_ui import browser_project as browser_project

ROOT = Path(__file__).resolve().parents[1]
API_SOURCE = ROOT / "src/electrochem_v6/ui/static/api.js"


def test_project_list_network_failure_recovers_real_records(browser_project):
    page, base_url, project_id = browser_project
    record_key = seed(project_id, "network-recovery", 2)
    attempts = []

    def intercept(route):
        attempts.append(route.request)
        if len(attempts) == 1:
            route.abort("failed")
        else:
            route.continue_()

    page.route("**/api/v1/projects?status=active", intercept)
    page.goto(base_url + "/ui", wait_until="networkidle")
    page.click("#tab-btn-project")
    page.locator(".project-record-check").wait_for(state="visible", timeout=8000)
    assert len(attempts) == 2
    assert all(request.method == "GET" for request in attempts)
    assert page.locator(".project-record-check").count() == 1
    assert page.locator(".project-record-check").get_attribute("data-record-key") == record_key
    assert "network-recovery" in page.locator("#project-history-list").inner_text()


def test_cross_realm_post_request_is_not_retried(browser_project):
    page, base_url, _project_id = browser_project
    attempts = []
    page.goto(base_url + "/ui", wait_until="networkidle")

    def intercept(route):
        attempts.append(route.request.method)
        route.abort("failed")

    page.route("**/api/v1/projects", intercept)
    result = page.evaluate("""async () => {
      const frame = document.createElement('iframe'); document.body.append(frame);
      try {
        const request = new frame.contentWindow.Request(location.origin + '/api/v1/projects', {
          method: 'POST',
        });
        const currentRealmRequest = request instanceof Request;
        try { await ElectrochemApi.fetch(request); return { unexpectedSuccess: true }; }
        catch (error) { return { currentRealmRequest, error: error.name }; }
      } finally { frame.remove(); }
    }""")
    assert result == {"currentRealmRequest": False, "error": "TypeError"}
    assert attempts == ["POST"]


def _run_api(scenario: str) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node executable is required for API boundary tests")
    script = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
const sandbox = {
  assert, URL, URLSearchParams, Request, Headers, AbortController, DOMException, queueMicrotask,
  document: { querySelector: () => ({ content: 'test-session' }) },
  CustomEvent: class { constructor(type) { this.type = type; } },
  window: {
    location: { href: 'http://127.0.0.1:8010/ui', origin: 'http://127.0.0.1:8010' },
    dispatchEvent: () => {}, setTimeout: callback => { queueMicrotask(callback); return 1; },
  },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(API_SOURCE, 'utf8'), sandbox);
vm.runInContext(SCENARIO, sandbox).then(() => console.log('passed')).catch(error => {
  console.error(error.stack); process.exitCode = 1;
});
"""
    code = (
        f"const API_SOURCE = {json.dumps(API_SOURCE.as_posix())};\n"
        f"const SCENARIO = {json.dumps('(async () => {' + scenario + '})()')};\n"
        + script
    )
    result = subprocess.run([node, "-e", code], cwd=ROOT, capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert result.stdout.strip() == "passed"


@pytest.mark.parametrize("fetch_args", [
    "['/api/v1/projects']",
    "[new URL('/api/v1/projects', window.location.href), { method: 'HEAD' }]",
    "[new Request(window.location.origin + '/api/v1/projects', { method: 'HEAD' })]",
    "[new Request(window.location.origin + '/api/v1/projects', { method: 'POST' }), { method: 'GET' }]",
    "['/health']",
])
def test_api_read_network_failure_retries_once_with_same_headers(fetch_args):
    _run_api(f"""
      const request = {fetch_args}, calls = [], waits = [], expected = {{ ok: true }};
      window.setTimeout = (callback, delay) => {{ waits.push(delay); queueMicrotask(callback); return 1; }};
      window.fetch = async (...args) => {{
        calls.push(args);
        if (calls.length === 1) throw new TypeError('Failed to fetch');
        return expected;
      }};
      assert.equal(await window.ElectrochemApi.fetch(...request), expected);
      assert.equal(calls.length, 2);
      assert.equal(calls[0][0], calls[1][0]);
      assert.equal(calls[0][1], calls[1][1]);
      assert.equal(calls[1][1].headers.get('X-Electrochem-Session'), String(request[0]).endsWith('/health') ? null : 'test-session');
      assert.deepEqual(waits, [150]);
      const failure = new TypeError('Still unavailable'); let count = 0;
      window.fetch = async () => {{ count++; throw failure; }};
      await assert.rejects(window.ElectrochemApi.fetch(...request), error => error === failure);
      assert.equal(count, 2);
    """)


@pytest.mark.parametrize("fetch_args", [
    "['/api/v1/projects', { method: 'POST' }]",
    "['/api/v1/projects', { method: 'PUT' }]",
    "['/api/v1/projects', { method: 'PATCH' }]",
    "['/api/v1/projects', { method: 'DELETE' }]",
    "[new Request(window.location.origin + '/api/v1/projects', { method: 'POST' })]",
    "[new Request(window.location.origin + '/api/v1/projects'), { method: 'POST' }]",
    "['https://example.invalid/api/v1/projects']",
    "['/ui/static/theme.js']",
])
def test_api_non_read_or_non_api_failure_is_not_retried(fetch_args):
    _run_api(f"""
      let count = 0, waits = 0;
      window.setTimeout = () => {{ waits++; }};
      const failure = new TypeError('Failed to fetch');
      window.fetch = async () => {{ count++; throw failure; }};
      await assert.rejects(window.ElectrochemApi.fetch(...{fetch_args}), error => error === failure);
      assert.equal(count, 1); assert.equal(waits, 0);
    """)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 503])
def test_api_http_error_response_is_returned_without_retry(status):
    _run_api(f"""
      const response = {{ ok: false, status: {status} }}; let count = 0;
      window.fetch = async () => {{ count++; return response; }};
      assert.equal(await window.ElectrochemApi.fetch('/api/v1/projects'), response);
      assert.equal(count, 1);
    """)


@pytest.mark.parametrize("mode", ["abort-error", "custom-abort", "inherited-signal", "during-delay"])
def test_api_cancelled_reads_do_not_send_a_second_request(mode):
    _run_api(f"""
      const mode = {json.dumps(mode)}, controller = new AbortController(); let count = 0, waits = 0;
      const custom = new TypeError('User cancelled'), aborted = new DOMException('Cancelled', 'AbortError');
      const input = mode === 'inherited-signal' ? new Request(window.location.origin + '/api/v1/projects', {{ signal: controller.signal }}) : '/api/v1/projects';
      const options = mode === 'inherited-signal' ? undefined : {{ signal: controller.signal }};
      window.setTimeout = callback => {{ waits++; controller.abort(custom); queueMicrotask(callback); return 1; }};
      window.fetch = async () => {{
        count++;
        if (mode === 'abort-error') throw aborted;
        if (mode !== 'during-delay') controller.abort(custom);
        throw custom;
      }};
      await assert.rejects(window.ElectrochemApi.fetch(input, options), error => error === (mode === 'abort-error' ? aborted : custom));
      assert.equal(count, 1); assert.equal(waits, mode === 'during-delay' ? 1 : 0);
    """)


def test_api_signal_override_and_non_network_errors():
    _run_api("""
      const controller = new AbortController(); controller.abort();
      const input = new Request(window.location.origin + '/api/v1/projects', { signal: controller.signal });
      for (const signal of [null, new AbortController().signal]) {
        let count = 0;
        window.fetch = async () => { count++; if (count === 1) throw new TypeError('Network'); return { ok: true }; };
        assert.equal((await window.ElectrochemApi.fetch(input, { signal })).ok, true);
        assert.equal(count, 2);
      }
      let count = 0; const failure = new Error('Unexpected implementation error');
      window.fetch = async () => { count++; throw failure; };
      await assert.rejects(window.ElectrochemApi.fetch('/api/v1/projects'), error => error === failure);
      assert.equal(count, 1);
    """)


def test_api_post_request_notifies_task_change_once_after_success():
    _run_api("""
      const events = []; let count = 0;
      window.dispatchEvent = event => events.push(event.type);
      window.fetch = async () => { count++; return { ok: true }; };
      await window.ElectrochemApi.fetch(new Request(window.location.origin + '/api/v1/process/jobs', { method: 'POST' }));
      assert.equal(count, 1); assert.deepEqual(events, ['electrochem:tasks-changed']);
      window.fetch = async () => { count++; return { ok: false, status: 503 }; };
      await window.ElectrochemApi.fetch('/api/v1/process/jobs', { method: 'POST' });
      assert.equal(count, 2); assert.deepEqual(events, ['electrochem:tasks-changed']);
    """)
