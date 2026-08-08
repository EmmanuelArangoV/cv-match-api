import uuid
from types import SimpleNamespace

import pytest

from src.api.v1.ai_config import CreateModelRequest, activate_model, create_model
from src.domain.shared.exceptions import BusinessRuleException


class _DatabaseWithUnknownModel:
    async def get(self, model_type: object, model_id: uuid.UUID) -> SimpleNamespace:
        return SimpleNamespace(provider="OPENAI", model_name="modelo-sin-tarifa")


async def test_create_openai_model_requires_auditable_pricing() -> None:
    request = CreateModelRequest(
        task_type="CV_MATCH",
        provider="OPENAI",
        model_name="modelo-sin-tarifa",
    )

    with pytest.raises(BusinessRuleException, match="tarifa auditable"):
        await create_model(
            request,
            current_user=SimpleNamespace(id=uuid.uuid4()),
            db=SimpleNamespace(),
        )


async def test_activate_openai_model_requires_auditable_pricing() -> None:
    with pytest.raises(BusinessRuleException, match="tarifa auditable"):
        await activate_model(
            uuid.uuid4(),
            current_user=SimpleNamespace(id=uuid.uuid4()),
            db=_DatabaseWithUnknownModel(),
        )
