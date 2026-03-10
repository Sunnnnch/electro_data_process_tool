import os
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from electrochem_v6.core.logging_policy import get_v6_logger, log_event, sanitize_for_log, summarize_payload  # noqa: E402


def test_sanitize_for_log_masks_sensitive_fields_and_tokens():
    payload = {
        "api_key": "sk-verysecretvalue123456",
        "nested": {"authorization": "Bearer ABCDEFGH1234567890"},
        "token_hint": "token_value_should_be_masked",
        "normal": "ok",
    }
    cleaned = sanitize_for_log(payload)
    assert cleaned["normal"] == "ok"
    assert "verysecretvalue" not in str(cleaned)
    assert "ABCDEFGH1234567890" not in str(cleaned)
    assert "***" in str(cleaned)


def test_summarize_payload_only_keeps_low_risk_fields():
    payload = {
        "api_key": "sk-raw-key-1234567890",
        "message": "Bearer secret-token-value",
        "status": "success",
        "x": 1,
    }
    summary = summarize_payload(payload)
    assert summary["status"] == "success"
    assert "keys" in summary
    assert "api_key" in summary["keys"]
    assert "secret-token-value" not in str(summary)


def test_log_event_write_masks_sensitive_values(tmp_path):
    old_log = os.environ.get("ELECTROCHEM_V6_LOG_FILE")
    old_include = os.environ.get("ELECTROCHEM_V6_LOG_INCLUDE_PAYLOAD")
    try:
        log_file = tmp_path / "v6_mask.log"
        os.environ["ELECTROCHEM_V6_LOG_FILE"] = str(log_file)
        os.environ["ELECTROCHEM_V6_LOG_INCLUDE_PAYLOAD"] = "1"
        logger = get_v6_logger(f"electrochem_v6.test.{uuid.uuid4().hex[:8]}")
        log_event(
            logger,
            "unit.test",
            {
                "api_key": "sk-raw-key-1234567890",
                "authorization": "Bearer secret-token-value",
                "message": "keep this visible",
            },
        )
        for h in logger.handlers:
            h.flush()
        text = log_file.read_text(encoding="utf-8")
        assert "sk-raw-key-1234567890" not in text
        assert "secret-token-value" not in text
        assert "***" in text
        assert "unit.test" in text
    finally:
        if old_log is None:
            os.environ.pop("ELECTROCHEM_V6_LOG_FILE", None)
        else:
            os.environ["ELECTROCHEM_V6_LOG_FILE"] = old_log
        if old_include is None:
            os.environ.pop("ELECTROCHEM_V6_LOG_INCLUDE_PAYLOAD", None)
        else:
            os.environ["ELECTROCHEM_V6_LOG_INCLUDE_PAYLOAD"] = old_include
