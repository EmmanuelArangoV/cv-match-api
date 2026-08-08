import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.v1 import webhooks


def _request(answered_by: str) -> SimpleNamespace:
    return SimpleNamespace(
        form=AsyncMock(
            return_value={
                "CallSid": "CA-test",
                "AnsweredBy": answered_by,
                "MachineDetectionDuration": "2100",
            }
        ),
        headers={"X-Twilio-Signature": "signature"},
        url=SimpleNamespace(path="/api/v1/webhooks/twilio/amd-status", query="run_id=run-1"),
    )


@pytest.mark.asyncio
async def test_async_amd_terminates_machine_and_queues_retry(monkeypatch) -> None:
    run = SimpleNamespace(
        id=uuid.uuid4(),
        twilio_call_sid="CA-test",
        amd_result=None,
        twilio_status_detail=None,
    )
    db = SimpleNamespace(commit=AsyncMock())
    end_call = MagicMock()
    retry = MagicMock()
    monkeypatch.setattr(webhooks, "_get_run_or_none", AsyncMock(return_value=run))
    monkeypatch.setattr(webhooks.twilio_client, "validate_twilio_signature", lambda *args: True)
    monkeypatch.setattr(webhooks.twilio_client, "end_call", end_call)
    monkeypatch.setattr(webhooks.retry_or_fail_profiling_call, "delay", retry)

    result = await webhooks.twilio_async_amd_webhook(_request("machine_start"), "run-1", db)

    assert result == {"status": "terminated"}
    assert run.amd_result == "machine_start"
    assert run.twilio_status_detail == "amd:machine_start:2100ms"
    end_call.assert_called_once_with("CA-test")
    retry.assert_called_once_with(str(run.id), "AMD:machine_start")


@pytest.mark.asyncio
async def test_async_amd_keeps_human_call_connected(monkeypatch) -> None:
    run = SimpleNamespace(
        id=uuid.uuid4(),
        twilio_call_sid="CA-test",
        amd_result=None,
        twilio_status_detail=None,
    )
    db = SimpleNamespace(commit=AsyncMock())
    end_call = MagicMock()
    monkeypatch.setattr(webhooks, "_get_run_or_none", AsyncMock(return_value=run))
    monkeypatch.setattr(webhooks.twilio_client, "validate_twilio_signature", lambda *args: True)
    monkeypatch.setattr(webhooks.twilio_client, "end_call", end_call)

    result = await webhooks.twilio_async_amd_webhook(_request("human"), "run-1", db)

    assert result == {"status": "ok"}
    assert run.amd_result == "human"
    end_call.assert_not_called()
