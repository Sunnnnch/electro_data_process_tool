"""Real loopback contention and session routing; no user instance is contacted."""

from __future__ import annotations

import json
import os
import socket
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import error, request

import pytest

from electrochem_v6.server import V6ServerManager
from electrochem_v6.store.runtime import reset_runtime


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    reset_runtime()
    yield
    reset_runtime()


@contextmanager
def running_manager(port=0):
    manager = V6ServerManager(port=port)
    ok, message = manager.start()
    assert ok, message
    try:
        yield manager
    finally:
        manager.stop()


def read(manager, route, *, body=None, token=None):
    headers = {}
    if token is not None:
        headers["X-Electrochem-Session"] = token
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(f"http://127.0.0.1:{manager.port}{route}", data=data, headers=headers)
    try:
        with request.urlopen(req, timeout=3) as response:
            return response.status, response.read().decode("utf-8")
    except error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def test_second_manager_cannot_claim_live_port_or_change_its_identity():
    with running_manager() as original:
        contender = V6ServerManager(port=original.port)
        try:
            ok, _ = contender.start()
            assert not ok, "A second instance must not claim a live service address"
            assert not contender.is_running and contender._server is None
            for _ in range(3):
                status, html = read(original, "/ui")
                assert status == 200 and original.session_token in html
                assert contender.session_token not in html
        finally:
            if contender.is_running:
                contender.stop()


def test_contender_can_retry_another_port_and_each_service_keeps_its_session():
    with running_manager() as original:
        contender = V6ServerManager(port=original.port)
        try:
            ok, _ = contender.start()
            assert not ok
            contender.port = 0
            ok, message = contender.start()
            assert ok, message
            assert contender.port != original.port
            for manager, other in ((original, contender), (contender, original)):
                status, html = read(manager, "/ui")
                assert status == 200 and manager.session_token in html
                assert other.session_token not in html
        finally:
            if contender.is_running:
                contender.stop()


@pytest.mark.skipif(os.name != "nt", reason="Windows legacy SO_REUSEADDR semantics")
def test_new_manager_rejects_port_occupied_by_legacy_reuseaddr_listener():
    class LegacyHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"legacy-owned-listener"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), LegacyHandler) as legacy:
        assert legacy.socket.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR) == 1
        thread = threading.Thread(target=legacy.serve_forever, daemon=True)
        thread.start()
        contender = V6ServerManager(port=legacy.server_port)
        try:
            ok, _ = contender.start()
            assert not ok, "Do not attach beside a prior build using SO_REUSEADDR"
            for _ in range(3):
                status, body = read(contender, "/")
                assert status == 200 and body == "legacy-owned-listener"
        finally:
            if contender.is_running:
                contender.stop()
            legacy.shutdown()
            thread.join(timeout=3)


@pytest.mark.skipif(os.name != "nt", reason="Windows exclusive-address enforcement")
def test_reuseaddr_socket_cannot_attach_to_new_manager():
    with running_manager() as manager, socket.socket() as contender:
        contender.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        with pytest.raises(OSError):
            contender.bind(("127.0.0.1", manager.port))


def test_wrong_explicit_native_session_cannot_create_project():
    with running_manager() as manager:
        for token in ("wrong-instance-token", manager.session_token + "different"):
            status, _ = read(manager, "/api/v1/projects", body={"name": "must-not-exist"}, token=token)
            assert status == 403
        status, listing = read(manager, "/api/v1/projects")
        assert status == 200 and json.loads(listing)["projects"] == []

        # The valid session and existing tokenless native-client contract work.
        for name, token in (("own-session", manager.session_token), ("native-no-token", None)):
            status, response = read(manager, "/api/v1/projects", body={"name": name}, token=token)
            assert status == 200 and json.loads(response)["project"]["name"] == name
        _, listing = read(manager, "/api/v1/projects")
        assert {item["name"] for item in json.loads(listing)["projects"]} == {"own-session", "native-no-token"}
