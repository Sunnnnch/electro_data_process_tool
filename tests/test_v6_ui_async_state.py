"""Exercise the actual UI entry points with controlled asynchronous responses."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "electrochem_v6" / "ui" / "static"


def _run_ui(script: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node executable is required for UI asynchronous state tests")
    harness = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const response = data => ({ ok: true, json: async () => data });
const conversation = (id, content = id) => response({
  status: 'success', conversation: { conversation_id: id, title: id, messages: [{ content }] },
});
const dom = {};
const element = id => dom[id] ||= { value: '', textContent: '', disabled: false, dataset: {} };
const api = {};
const sandbox = {
  assert, deferred, response, conversation, dom, api, element, URLSearchParams,
  setTimeout: callback => { queueMicrotask(callback); return 1; },
  window: {
    setTimeout: callback => { queueMicrotask(callback); return 1; },
    ElectrochemAssistantApi: api,
    ElectrochemAssistantPage: {
      renderMessages: ({ messages }) => { element('chat-log').messages = messages; },
      renderConversations: ({ items, currentConversationId }) => {
        element('conv-list').items = items;
        element('conv-list').selected = currentConversationId;
      },
      appendLocalMessage: () => {}, showTypingIndicator: () => {}, removeTypingIndicator: () => {},
    },
  },
  document: { getElementById: element, querySelectorAll: () => [] },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(STATIC_ROOT + '/process_runtime.js', 'utf8'), sandbox);
const source = fs.readFileSync(STATIC_ROOT + '/app.js', 'utf8');
assert.match(source, /\ninit\(\);\s*$/);
// Only suppress DOM startup; all state variables and entry points are the real app.
vm.runInContext(source.replace(/\ninit\(\);\s*$/, '\n'), sandbox);
    vm.runInContext('getActivePromptPrefix = () => ""; refreshAssistantContextPreview = () => null; buildAssistantActionContext = async () => null;', sandbox);
vm.runInContext(SCENARIO, sandbox).then(result => console.log(JSON.stringify(result))).catch(error => {
  console.error(error.stack); process.exitCode = 1;
});
"""
    code = (
        f"const STATIC_ROOT = {json.dumps(STATIC.as_posix())};\n"
        f"const SCENARIO = {json.dumps('(async () => {' + script + '})()')};\n"
        + harness
    )
    result = subprocess.run(
        [node, "-e", code], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert result.stdout.strip(), "UI scenario did not finish"
    return json.loads(result.stdout)


def test_conversation_detail_ignores_reversed_and_same_conversation_responses() -> None:
    result = _run_ui("""
      const requests = [];
      api.getConversation = id => {
        const pending = deferred(); requests.push({ id, ...pending }); return pending.promise;
      };
      const openA = openConversation('A', true);
      const openB = openConversation('B', true);
      assert.equal(element('chat-log').messages.length, 0);
      requests[1].resolve(conversation('B'));
      await openB;
      requests[0].resolve(conversation('A'));
      await openA;
      assert.equal(currentConversationId, 'B');
      assert.equal(element('conv-title').textContent, 'B');
      assert.equal(element('chat-log').messages[0].content, 'B');
      const oldReload = openConversation('B', true);
      const newReload = openConversation('B', true);
      requests[3].resolve(conversation('B', 'newest'));
      await newReload;
      requests[2].resolve(conversation('B', 'outdated'));
      await oldReload;
      assert.equal(element('chat-log').messages[0].content, 'newest');
      const oldError = openConversation('A', true);
      startNewConversation();
      requests[4].reject(new Error('late network failure'));
      await oldError;
      assert.equal(currentConversationId, null);
      assert.equal(element('conv-title').textContent, 'conv_new');
      assert.equal(element('send-status').textContent, 'conv_new');
      return { selected: currentConversationId, title: element('conv-title').textContent };
    """)
    assert result == {"selected": None, "title": "conv_new"}


def test_conversation_search_keeps_selection_and_latest_list() -> None:
    result = _run_ui("""
      api.getConversation = async id => conversation(id);
      await openConversation('A', true);
      const searches = [];
      api.listConversations = options => {
        const pending = deferred(); searches.push({ ...pending, keyword: options.keyword }); return pending.promise;
      };
      currentConversationKeyword = 'B';
      const oldSearch = loadConversations();
      currentConversationKeyword = 'C';
      const newSearch = loadConversations();
      searches[1].resolve(response({ status: 'success', items: [{ conversation_id: 'C' }] }));
      await newSearch;
      searches[0].resolve(response({ status: 'success', items: [{ conversation_id: 'B' }] }));
      await oldSearch;
      assert.equal(currentConversationId, 'A');
      assert.equal(element('conv-title').textContent, 'A');
      assert.equal(element('chat-log').messages[0].content, 'A');
      assert.equal(element('conv-list').items[0].conversation_id, 'C');
      const refreshed = loadConversations();
      startNewConversation();
      searches[2].resolve(response({ status: 'success', items: [{ conversation_id: 'A' }] }));
      await refreshed;
      assert.equal(currentConversationId, null);
      assert.equal(element('conv-title').textContent, 'conv_new');
      return { selected: currentConversationId, title: element('conv-title').textContent };
    """)
    assert result == {"selected": None, "title": "conv_new"}


def test_initial_list_does_not_override_new_conversation_created_while_loading() -> None:
    result = _run_ui("""
      const pending = deferred();
      let detailLoads = 0;
      api.listConversations = () => pending.promise;
      api.getConversation = async id => { detailLoads += 1; return conversation(id); };
      const loading = loadConversations();
      startNewConversation();
      pending.resolve(response({ status: 'success', items: [{ conversation_id: 'A' }] }));
      await loading;
      assert.equal(currentConversationId, null);
      assert.equal(detailLoads, 0);
      return { detailLoads };
    """)
    assert result == {"detailLoads": 0}


@pytest.mark.parametrize("navigation", ["switch", "new", "fresh-new"])
@pytest.mark.parametrize("job_status", ["succeeded", "failed"])
def test_old_agent_job_does_not_replace_later_view_or_draft(navigation: str, job_status: str) -> None:
    result = _run_ui(f"""
      const navigation = {json.dumps(navigation)};
      const jobStatus = {json.dumps(job_status)};
      const polled = deferred();
      const result = deferred();
      const submits = [];
      api.getConversation = async id => conversation(id);
      api.listConversations = async () => response({{ status: 'success', items: [{{ conversation_id: 'A' }}, {{ conversation_id: 'B' }}] }});
      api.submitMessageJob = async payload => {{ submits.push(payload); return response({{ status: 'success', job_id: 'job-A' }}); }};
      api.getMessageJob = jobId => {{ assert.equal(jobId, 'job-A'); polled.resolve(); return result.promise; }};
      if (navigation !== 'fresh-new') await openConversation('A', true);
      element('msg-input').value = 'first message';
      const sending = sendMessage();
      await sendMessage();
      assert.equal(submits.length, 1);
      await polled.promise;
      if (navigation === 'switch') await openConversation('B', true);
      else startNewConversation();
      element('msg-input').value = 'draft for later view';
      result.resolve(response({{ status: 'success', job: {{ status: jobStatus, error: 'old job failed', result: {{
        status: 'success', conversation_id: 'A', conversation: {{ conversation_id: 'A', title: 'A', messages: [{{ content: 'late A reply' }}] }},
      }} }} }}));
      await sending;
      assert.equal(currentConversationId, navigation === 'switch' ? 'B' : null);
      assert.equal(element('conv-title').textContent, navigation === 'switch' ? 'B' : 'conv_new');
      assert.equal(element('msg-input').value, 'draft for later view');
      assert.equal(element('send-btn').disabled, false);
      assert.equal(activeAgentJobId, null);
      assert.equal(activeAgentRequest, null);
      assert.equal(element('chat-log').messages.some(item => item.content === 'late A reply'), false);
      return {{ submissions: submits.length, selected: currentConversationId }};
    """)
    assert result == {"submissions": 1, "selected": "B" if navigation == "switch" else None}


def test_agent_polling_completion_cannot_clear_another_job() -> None:
    result = _run_ui("""
      const polls = { old: deferred(), newer: deferred() };
      const entered = { old: deferred(), newer: deferred() };
      const calls = [];
      api.getMessageJob = id => { calls.push(id); entered[id].resolve(); return polls[id].promise; };
      const old = waitForAgentJob('old', null).catch(error => error.message);
      await entered.old.promise;
      const newer = waitForAgentJob('newer', null);
      await entered.newer.promise;
      polls.old.resolve(response({ status: 'success', job: { status: 'succeeded', result: { id: 'old' } } }));
      await old;
      assert.equal(activeAgentJobId, 'newer');
      polls.newer.resolve(response({ status: 'success', job: { status: 'succeeded', result: { id: 'newer' } } }));
      assert.equal((await newer).id, 'newer');
      assert.equal(activeAgentJobId, null);
      return { calls };
    """)
    assert result == {"calls": ["old", "newer"]}


def test_process_double_click_is_locked_through_preflight_submission_and_polling() -> None:
    result = _run_ui("""
      const runtime = window.ElectrochemProcessRuntime;
      const preflight = deferred(), submit = deferred(), submitted = deferred(), polled = deferred(), terminal = deferred();
      const cancel = deferred();
      let active = '', disabled = false, preflightCalls = 0, submissions = 0;
      const cancellations = [], polls = [], progress = [];
      const processApi = {
        submitProcessJob: () => { submissions += 1; submitted.resolve(); return submit.promise; },
        getProcessJob: id => { polls.push(id); polled.resolve(); return terminal.promise; },
        cancelProcessJob: id => { cancellations.push(id); return cancel.promise; },
      };
      const context = () => ({
        processingApi: processApi, getActiveProcessJobId: () => active,
        setActiveProcessJob: id => { active = id; }, setProcessSubmitting: value => { disabled = value; },
        collectProcessPayload: () => ({ folder_path: 'same-source' }),
        runPreflight: () => { preflightCalls += 1; return preflight.promise; },
        setProcStatus: () => {}, setProcessRunState: () => {}, updateProcessStepState: () => {},
        updateProcessJobProgress: job => progress.push(job.job_id),
        renderProcessResult: () => {}, renderProcessError: () => {},
        loadStatsAndHistory: async () => {}, loadProjects: async () => {}, t: key => key,
      });
      const first = runtime.runProcess(context());
      await runtime.runProcess(context());
      assert.equal(disabled, true);
      assert.equal(preflightCalls, 1);
      preflight.resolve({});
      await submitted.promise;
      await runtime.runProcess(context());
      assert.equal(submissions, 1);
      submit.resolve(response({ status: 'success', job_id: 'only-job', job: { job_id: 'only-job', status: 'running' } }));
      await polled.promise;
      assert.equal(disabled, false);
      const cancelling = runtime.runProcess(context());
      assert.equal(cancellations.join(','), 'only-job');
      terminal.resolve(response({ status: 'success', job: { job_id: 'only-job', status: 'succeeded', result: { status: 'success', result: {} } } }));
      await first;
      assert.equal(active, '');
      assert.equal(disabled, false);
      // A delayed cancellation response from the old run must not clear its successor.
      const secondPoll = deferred(), secondEntered = deferred();
      processApi.submitProcessJob = async () => { submissions += 1; return response({ status: 'success', job_id: 'next-job' }); };
      processApi.getProcessJob = id => { assert.equal(id, 'next-job'); secondEntered.resolve(); return secondPoll.promise; };
      const next = runtime.runProcess(context());
      await secondEntered.promise;
      cancel.resolve(response({ status: 'success' }));
      await cancelling;
      assert.equal(active, 'next-job');
      secondPoll.resolve(response({ status: 'success', job: { status: 'cancelled', job_id: 'next-job' } }));
      await next;
      assert.equal(active, '');
      return { preflightCalls, submissions, polls, cancellations, disabled };
    """)
    assert result == {
        "preflightCalls": 2, "submissions": 2, "polls": ["only-job"],
        "cancellations": ["only-job"], "disabled": False,
    }


@pytest.mark.parametrize("failure_stage", ["preflight", "submission"])
def test_process_submission_lock_is_released_after_failure(failure_stage: str) -> None:
    result = _run_ui(f"""
      const runtime = window.ElectrochemProcessRuntime;
      let fail = true, disabled = false, completed = 0;
      const ctx = {{
        processingApi: {{
          submitProcessJob: async () => {{
            if (fail) throw new Error('submission failed');
            return response({{ status: 'success', job_id: 'retry', job: {{ status: 'succeeded', result: {{ status: 'success', result: {{}} }} }} }});
          }},
          getProcessJob: async () => {{ throw new Error('unexpected poll'); }},
        }},
        collectProcessPayload: () => ({{}}),
        runPreflight: async () => {{ if (fail && {json.dumps(failure_stage)} === 'preflight') throw new Error('preflight failed'); }},
        setProcessSubmitting: value => {{ disabled = value; }},
        setProcStatus: () => {{}}, setProcessRunState: () => {{}}, updateProcessStepState: () => {{}},
        renderProcessResult: () => {{ completed += 1; }}, renderProcessError: () => {{}},
        loadStatsAndHistory: async () => {{}}, loadProjects: async () => {{}}, t: key => key,
      }};
      assert.equal(await runtime.runProcess(ctx), null);
      assert.equal(disabled, false);
      fail = false;
      await runtime.runProcess(ctx);
      assert.equal(completed, 1);
      assert.equal(disabled, false);
      return {{ completed, disabled }};
    """)
    assert result == {"completed": 1, "disabled": False}
