"""Existing conversations must honor effective client settings on every turn."""

from copy import deepcopy

import pytest

from electrochem_v6.agent import service
from electrochem_v6.llm.config import LLMConfig


class RecordingClient:
    def __init__(self, provider, model, entry, key):
        self.provider = provider
        self.model = model
        self.entry = entry
        self.key = key
        self.calls = []

    def stream_chat(self, *_args, **_kwargs):
        raise NotImplementedError

    def chat(self, messages, **_kwargs):
        self.calls.append(deepcopy(messages))
        return {"content": f"reply:{self.provider}/{self.model}"}


@pytest.fixture
def configured_service(monkeypatch, tmp_path):
    monkeypatch.setenv("ELECTROCHEM_V6_LLM_CONFIG_FILE", str(tmp_path / "llm.json"))
    for name in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    cfg = LLMConfig()
    assert cfg.update_model_entry("openai", {"model": "old-model", "api_key": "test-old-key"})
    assert cfg.update_model_entry("deepseek", {"model": "new-model", "api_key": "test-new-key"})
    created = []

    def create(config, provider=None, model_override=None):
        client = RecordingClient(
            provider, model_override, config.get_model_config(provider), config.get_api_key(provider),
        )
        created.append(client)
        return client

    monkeypatch.setattr(service, "create_llm_client", create)
    return service.AgentService(), cfg, created


def test_changed_provider_and_model_retain_conversation_context(configured_service):
    svc, _cfg, clients = configured_service
    first = svc.chat(message="original question", provider="openai", model="old-model")
    cid = first["conversation_id"]
    original = svc._sessions[cid]
    original.system_prompt = "custom instructions"
    original.max_iterations = 4
    context = deepcopy(original.conversation_history)

    second = svc.chat(message="follow up", conversation_id=cid, provider="deepseek", model="new-model")

    assert second["status"] == "success"
    assert (second["provider"], second["model"]) == ("deepseek", "new-model")
    assert len(clients) == 2
    assert clients[1].calls[0][0] == {"role": "system", "content": "custom instructions"}
    assert clients[1].calls[0][1:-1] == context
    assert svc._sessions[cid].max_iterations == 4
    assert second["conversation_id"] == cid
    assert second["messages"][-1]["metadata"]["model"] == "new-model"


@pytest.mark.parametrize("change", ["model", "base_url", "api_key", "timeout", "extra_headers", "env_key"])
def test_saved_and_environment_changes_refresh_existing_clients(configured_service, monkeypatch, change):
    svc, cfg, clients = configured_service
    first = svc.chat(message="first", provider="openai")
    cid = first["conversation_id"]
    values = {
        "model": "updated-model",
        "base_url": "https://example.invalid/v1",
        "api_key": "test-replaced-key",
        "timeout": 25,
        "extra_headers": {"X-Test": "updated"},
    }
    if change == "env_key":
        monkeypatch.setenv("OPENAI_API_KEY", "test-environment-key")
    else:
        assert cfg.update_model_entry("openai", {change: values[change]})
    result = svc.chat(message="second", conversation_id=cid, provider="openai")

    assert result["status"] == "success"
    assert len(clients) == 2
    if change == "env_key":
        assert clients[-1].key == "test-environment-key"
    elif change == "api_key":
        assert clients[-1].key == values[change]
    else:
        assert clients[-1].entry[change] == values[change]
    assert any(item["content"] == "first" for item in clients[-1].calls[0])


def test_unchanged_effective_settings_reuse_client(configured_service):
    svc, cfg, clients = configured_service
    first = svc.chat(message="first", provider="openai", model="explicit-model")
    assert cfg.update_model_entry("deepseek", {"timeout": 23})
    assert cfg.update_model_entry("openai", {"model": "unused-default"})
    result = svc.chat(
        message="second", conversation_id=first["conversation_id"], provider="openai-compatible", model="explicit-model",
    )
    assert result["status"] == "success"
    assert len(clients) == 1
    assert len(clients[0].calls) == 2


def test_refresh_failure_does_not_use_old_client_or_lose_history(configured_service, monkeypatch):
    svc, _cfg, clients = configured_service
    first = svc.chat(message="first", provider="openai")
    cid = first["conversation_id"]
    previous = svc._sessions[cid]
    before = deepcopy(previous.conversation_history)

    def broken(*_args, **_kwargs):
        raise ValueError("replacement configuration is invalid")

    monkeypatch.setattr(service, "create_llm_client", broken)
    result = svc.chat(message="second", conversation_id=cid, provider="deepseek")
    assert result["status"] == "error"
    assert svc._sessions[cid] is previous
    assert previous.conversation_history == before
    assert len(clients[0].calls) == 1


def test_real_openai_factory_refreshes_sdk_default_headers(monkeypatch, tmp_path):
    import openai

    monkeypatch.setenv("ELECTROCHEM_V6_LLM_CONFIG_FILE", str(tmp_path / "llm.json"))
    cfg = LLMConfig()
    assert cfg.update_model_entry("openai", {
        "api_key": "test-key", "extra_headers": {"X-Tenant": "before"},
    })
    sdk_settings = []

    def sdk(**kwargs):
        sdk_settings.append(kwargs)
        return object()

    monkeypatch.setattr(openai, "OpenAI", sdk)
    svc = service.AgentService()
    before, _, _ = svc._agent_for_request("headers", "openai", None)
    before.conversation_history = [{"role": "user", "content": "previous context"}]
    assert cfg.update_model_entry("openai", {"extra_headers": {"X-Tenant": "after"}})
    after, _, _ = svc._agent_for_request("headers", "openai", None)
    assert sdk_settings[0]["default_headers"] == {"X-Tenant": "before"}
    assert sdk_settings[1]["default_headers"] == {"X-Tenant": "after"}
    assert after.conversation_history == before.conversation_history
