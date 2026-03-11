import socket

from electrochem_v6.stress import run_stress_smoke


def _get_free_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    _, port = sock.getsockname()
    sock.close()
    return port


def test_v6_stress_smoke_minimal():
    port = _get_free_port()
    result = run_stress_smoke(
        port=port,
        upload_workers=2,
        upload_requests=2,
        conversation_turns=4,
        timeout_sec=8.0,
    )
    assert result.get("ok") is True
    phases = result.get("phases") or []
    assert len(phases) == 2
    assert phases[0].get("name") == "concurrent_upload"
    assert phases[1].get("name") == "long_conversation"
    assert phases[1].get("stored_messages", 0) >= 8

