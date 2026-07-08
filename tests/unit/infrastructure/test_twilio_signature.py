from twilio.request_validator import RequestValidator

from src.config import settings
from src.infrastructure.voice.twilio_client import validate_twilio_signature

_URL = "https://example.ngrok.io/api/v1/webhooks/twilio/twiml?run_id=abc-123"
_PARAMS = {"CallSid": "CA123", "AnsweredBy": "human"}


def test_valid_signature_passes(monkeypatch):
    monkeypatch.setattr(settings, "twilio_validate_signature", True)
    monkeypatch.setattr(settings, "twilio_auth_token", "test-auth-token")

    validator = RequestValidator("test-auth-token")
    signature = validator.compute_signature(_URL, _PARAMS)

    assert validate_twilio_signature(_URL, _PARAMS, signature) is True


def test_invalid_signature_fails(monkeypatch):
    monkeypatch.setattr(settings, "twilio_validate_signature", True)
    monkeypatch.setattr(settings, "twilio_auth_token", "test-auth-token")

    assert validate_twilio_signature(_URL, _PARAMS, "sha1=not-a-real-signature") is False


def test_missing_signature_fails(monkeypatch):
    monkeypatch.setattr(settings, "twilio_validate_signature", True)
    monkeypatch.setattr(settings, "twilio_auth_token", "test-auth-token")

    assert validate_twilio_signature(_URL, _PARAMS, None) is False


def test_validation_disabled_always_passes(monkeypatch):
    monkeypatch.setattr(settings, "twilio_validate_signature", False)

    assert validate_twilio_signature(_URL, _PARAMS, None) is True
