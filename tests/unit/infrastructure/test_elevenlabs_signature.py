import hashlib
import hmac
import time

import pytest
from elevenlabs.errors.bad_request_error import BadRequestError

from src.config import settings
from src.infrastructure.voice.elevenlabs_client import verify_webhook_signature

_SECRET = "test-webhook-secret"
_RAW_BODY = '{"type": "post_call_transcription", "data": {"conversation_id": "conv-1"}}'


def _build_signature(raw_body: str, secret: str, timestamp: int | None = None) -> str:
    ts = timestamp if timestamp is not None else int(time.time())
    message = f"{ts}.{raw_body}"
    digest = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"t={ts},v0={digest}"


def test_valid_signature_returns_parsed_payload(monkeypatch):
    monkeypatch.setattr(settings, "elevenlabs_webhook_secret_transcription", _SECRET)
    signature = _build_signature(_RAW_BODY, _SECRET)

    event = verify_webhook_signature(_RAW_BODY, signature)

    assert event["data"]["conversation_id"] == "conv-1"


def test_invalid_signature_raises(monkeypatch):
    monkeypatch.setattr(settings, "elevenlabs_webhook_secret_transcription", _SECRET)
    signature = _build_signature(_RAW_BODY, "wrong-secret")

    with pytest.raises(BadRequestError):
        verify_webhook_signature(_RAW_BODY, signature)


def test_missing_signature_header_raises(monkeypatch):
    monkeypatch.setattr(settings, "elevenlabs_webhook_secret_transcription", _SECRET)

    with pytest.raises(BadRequestError):
        verify_webhook_signature(_RAW_BODY, None)
