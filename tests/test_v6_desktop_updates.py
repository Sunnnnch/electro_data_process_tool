"""Read-only update checks cannot redirect the desktop to third-party downloads."""

from __future__ import annotations

import json

import pytest
import requests

from electrochem_v6.desktop import updates


def release(tag="v6.0.21", *, prerelease=False, draft=False, legacy=False):
    prefix = "ElectroChemV6" if legacy else "ElectroChem"
    installer = f"{prefix}-Setup-{tag.lstrip('vV')}.exe"
    return {
        "tag_name": tag, "name": f"Release {tag}", "body": "Changes\n<script>untrusted notes</script>",
        "draft": draft, "prerelease": prerelease, "published_at": "2026-09-07T00:00:00Z",
        "html_url": f"{updates.RELEASES_URL}/tag/{tag}",
        "assets": [{"name": name, "browser_download_url": f"{updates.RELEASES_URL}/download/{tag}/{name}",
                    "state": "uploaded", "size": size} for name, size in ((installer, 10000), (f"{installer}.sha256", 100))],
    }


class Response:
    def __init__(self, payload, status=200, url=updates.API_URL):
        self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.status_code = status
        self.url = url
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def iter_content(self, chunk_size):
        for start in range(0, len(self.payload), chunk_size):
            yield self.payload[start:start + chunk_size]


class Transport:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []
        self.closed = False
        self.trust_env = True

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response

    def close(self):
        self.closed = True


def check(payload, current="6.0.20", **kwargs):
    transport = Transport(Response(payload, **kwargs))
    return updates.check_for_updates(current, session=transport), transport


def test_explicit_check_uses_only_official_metadata_and_fixed_navigation_target():
    result, transport = check([release()])
    assert result["status"] == "success"
    assert result["state"] == "update_available"
    assert result["update_available"] is True
    assert result["latest_version"] == "6.0.21"
    assert result["release_url"] == "https://github.com/Sunnnnch/electro_data_process_tool/releases"
    assert "<script>" in result["release_notes"]  # Caller renders notes as plain text.
    assert len(transport.calls) == 1
    url, kwargs = transport.calls[0]
    assert url == updates.API_URL
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == (3.0, 5.0)
    assert kwargs["stream"] is True
    assert "Authorization" not in kwargs["headers"]
    assert transport.response.closed
    assert "browser_download_url" not in result
    assert "signature_verified" not in result


def test_previous_release_installer_names_remain_discoverable():
    result, _ = check([release(legacy=True)])
    assert result["state"] == "update_available"
    assert result["installer_name"] == "ElectroChemV6-Setup-6.0.21.exe"


def test_current_installer_name_is_preferred_when_both_names_are_published():
    raw = release(legacy=True)
    raw["assets"].extend(release()["assets"])
    result, _ = check([raw])
    assert result["installer_name"] == "ElectroChem-Setup-6.0.21.exe"


def test_checksum_from_legacy_name_cannot_complete_a_new_name_release():
    raw = release()
    raw["assets"][1] = release(legacy=True)["assets"][1]
    result, _ = check([raw])
    assert result["state"] == "no_release"


@pytest.mark.parametrize(("current", "tags", "latest", "available"), [
    ("6.0.20", ["v6.0.21", "v7.0.1"], "7.0.1", True),
    ("7.0.1", ["v6.0.20", "v7.0.1"], "7.0.1", False),
    ("6.0.20", ["v6.0.21", "v6.1.0-rc.1"], "6.0.21", True),
    ("6.1.0-rc.1", ["v6.1.0-rc.2", "v6.0.22"], "6.1.0-rc.2", True),
    ("6.1.0-rc.10", ["v6.1.0-rc.2", "v6.1.0-rc.9"], "6.1.0-rc.9", False),
    ("6.1.0-rc.10", ["v6.1.0", "v6.1.0-rc.11"], "6.1.0", True),
    ("6.0.21+build.1", ["v6.0.21+build.2"], "6.0.21+build.2", False),
    ("6.0.99", ["v6.0.21", "v6.0.22"], "6.0.22", False),
    ("6.0.21", ["v6.0.21"], "6.0.21", False),
])
def test_semantic_order_and_prerelease_channel(current, tags, latest, available):
    result, _ = check([release(tag, prerelease="-" in tag) for tag in tags], current)
    assert result["latest_version"] == latest
    assert result["update_available"] is available


@pytest.mark.parametrize("version", ["6.0", "6.0.01", "6.0.20-01", "6.0.20-rc..1", "6.0.20+bad..build", "../v6.0.20", "6.0.20\n", "6.0.2０"])
def test_invalid_current_version_does_not_make_any_network_request(version):
    transport = Transport()
    result = updates.check_for_updates(version, session=transport)
    assert result["state"] == "invalid_version"
    assert transport.calls == []


@pytest.mark.parametrize("field", ["html_url", "asset_url", "asset_name", "userinfo", "port", "fragment", "query", "whitespace", "control"])
def test_release_or_asset_origin_cannot_escape_the_official_repository(field):
    raw = release()
    if field == "asset_url":
        raw["assets"][0]["browser_download_url"] = "https://github.com/attacker/repo/releases/download/v6.0.21/setup.exe"
    elif field == "asset_name":
        raw["assets"][0]["name"] = "../setup.exe"
    else:
        raw["html_url"] = {
            "html_url": "https://github.com.evil.example/Sunnnnch/electro_data_process_tool/releases/tag/v6.0.21",
            "userinfo": "https://attacker@github.com/Sunnnnch/electro_data_process_tool/releases/tag/v6.0.21",
            "port": raw["html_url"].replace("github.com", "github.com:444"),
            "fragment": raw["html_url"] + "#run-this",
            "query": raw["html_url"] + "?next=https://evil.example",
            "whitespace": " " + raw["html_url"],
            "control": raw["html_url"].replace("github", "git\nhub"),
        }[field]
    result, transport = check([raw])
    assert result["state"] == "invalid_response"
    assert result["update_available"] is False
    assert result["release_url"] == updates.RELEASES_URL
    assert len(transport.calls) == 1


@pytest.mark.parametrize("kind", ["draft", "prerelease", "missing_checksum", "pending_upload", "unversioned"])
def test_incomplete_or_ineligible_release_is_not_offered(kind):
    raw = release()
    if kind in ("draft", "prerelease"):
        raw[kind] = True
    elif kind == "missing_checksum":
        raw["assets"].pop()
    elif kind == "pending_upload":
        raw["assets"][0]["state"] = "new"
    else:
        raw["tag_name"] = "nightly"
    result, _ = check([raw])
    assert result["state"] == "no_release"
    assert result["update_available"] is False


@pytest.mark.parametrize(("error", "state"), [(requests.Timeout(), "timeout"), (requests.ConnectionError("private diagnostic"), "offline")])
def test_network_failures_are_bounded_and_do_not_expose_connection_details(error, state):
    result = updates.check_for_updates("6.0.20", session=Transport(error=error))
    assert result["state"] == state
    assert "private diagnostic" not in str(result)
    assert result["update_available"] is False


@pytest.mark.parametrize(("status", "state"), [(301, "invalid_response"), (403, "rate_limited"), (429, "rate_limited"), (404, "no_release"), (500, "invalid_response")])
def test_http_responses_do_not_trigger_redirects_or_downloads(status, state):
    result, transport = check([], status=status)
    assert result["state"] == state
    assert len(transport.calls) == 1


def test_size_limit_and_json_shape_are_checked():
    for payload in (b"x" * (updates.MAX_RESPONSE_BYTES + 1), b"not JSON", {"message": "unexpected"}, [release()] * 101):
        result, _ = check(payload)
        assert result["state"] == "invalid_response"


def test_owned_session_does_not_load_netrc_and_is_always_closed(monkeypatch):
    transport = Transport(Response([release()]))
    monkeypatch.setattr(updates.requests, "Session", lambda: transport)
    result = updates.check_for_updates("6.0.20")
    assert result["state"] == "update_available"
    assert transport.trust_env is False
    assert transport.closed
