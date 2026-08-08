from types import SimpleNamespace
from unittest.mock import MagicMock

from src.config import settings
from src.infrastructure.voice import twilio_client


def _mock_twilio(monkeypatch) -> MagicMock:
    create = MagicMock(return_value=SimpleNamespace(sid="CA-test"))
    client = SimpleNamespace(calls=SimpleNamespace(create=create))
    monkeypatch.setattr(twilio_client, "_get_client", lambda: client)
    monkeypatch.setattr(settings, "public_base_url", "https://api.example.test/")
    monkeypatch.setattr(settings, "twilio_from_number", "+15550000001")
    monkeypatch.setattr(settings, "twilio_ring_timeout_seconds", 25)
    monkeypatch.setattr(settings, "machine_detection_timeout", 10)
    return create


def test_outbound_call_keeps_amd_disabled_by_default(monkeypatch):
    create = _mock_twilio(monkeypatch)
    monkeypatch.setattr(settings, "twilio_machine_detection_enabled", False)

    assert twilio_client.create_outbound_call("+15550000002", "run-1") == "CA-test"

    params = create.call_args.kwargs
    assert "machine_detection" not in params
    assert "machine_detection_timeout" not in params


def test_outbound_call_enables_synchronous_amd_with_feature_flag(monkeypatch):
    create = _mock_twilio(monkeypatch)
    monkeypatch.setattr(settings, "twilio_machine_detection_enabled", True)

    twilio_client.create_outbound_call("+15550000002", "run-2")

    params = create.call_args.kwargs
    assert params["machine_detection"] == "Enable"
    assert params["machine_detection_timeout"] == 10
