import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import RequireAdmin, get_current_user
from src.domain.shared.exceptions import NotFoundException
from src.infrastructure.db.database import get_db
from src.infrastructure.db.models import (
    AIModelConfiguration,
    AIPrompt,
    GlobalBusinessSetting,
    User,
)

router = APIRouter(prefix="/ai-config", tags=["AI Config"])


def _serialize_model(m: AIModelConfiguration) -> dict:
    return {
        "id": str(m.id),
        "task_type": m.task_type,
        "provider": m.provider,
        "model_name": m.model_name,
        "is_active": m.is_active,
        "updated_by": str(m.updated_by) if m.updated_by else None,
        "updated_at": m.updated_at.isoformat(),
    }


def _serialize_prompt(p: AIPrompt) -> dict:
    return {
        "id": str(p.id),
        "task_type": p.task_type,
        "version_name": p.version_name,
        "system_prompt_text": p.system_prompt_text,
        "is_active": p.is_active,
        "updated_by": str(p.updated_by) if p.updated_by else None,
        "updated_at": p.updated_at.isoformat(),
    }


def _serialize_setting(s: GlobalBusinessSetting) -> dict:
    return {
        "id": str(s.id),
        "setting_key": s.setting_key,
        "setting_value": s.setting_value,
        "updated_by": str(s.updated_by) if s.updated_by else None,
        "updated_at": s.updated_at.isoformat(),
    }


# ─── Modelos de IA ─────────────────────────────────────────────────────────────


@router.get("/models")
async def list_models(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(AIModelConfiguration).order_by(AIModelConfiguration.task_type))
    return {"models": [_serialize_model(m) for m in result.scalars().all()]}


class CreateModelRequest(BaseModel):
    task_type: str
    provider: str
    model_name: str
    api_key_secret_ref: str | None = None


@router.post("/models", status_code=201)
async def create_model(
    body: CreateModelRequest,
    current_user: User = RequireAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict:
    model = AIModelConfiguration(
        task_type=body.task_type,
        provider=body.provider,
        model_name=body.model_name,
        api_key_secret_ref=body.api_key_secret_ref,
        is_active=False,
        updated_by=current_user.id,
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return _serialize_model(model)


@router.patch("/models/{model_id}/activate")
async def activate_model(
    model_id: uuid.UUID,
    current_user: User = RequireAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Activa este modelo y desactiva los demás con el mismo task_type (exclusión mutua)."""
    model = await db.get(AIModelConfiguration, model_id)
    if not model:
        raise NotFoundException("Configuración de modelo no encontrada")

    siblings = await db.execute(
        select(AIModelConfiguration).where(AIModelConfiguration.task_type == model.task_type)
    )
    for sibling in siblings.scalars().all():
        sibling.is_active = sibling.id == model.id
        sibling.updated_by = current_user.id

    await db.commit()
    await db.refresh(model)
    return _serialize_model(model)


# ─── Prompts (append-only) ──────────────────────────────────────────────────────


@router.get("/prompts")
async def list_prompts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(AIPrompt).order_by(AIPrompt.task_type, AIPrompt.created_at.desc())
    )
    return {"prompts": [_serialize_prompt(p) for p in result.scalars().all()]}


class CreatePromptRequest(BaseModel):
    task_type: str
    version_name: str
    system_prompt_text: str
    activate: bool = False


@router.post("/prompts", status_code=201)
async def create_prompt(
    body: CreatePromptRequest,
    current_user: User = RequireAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Append-only: nunca se edita un prompt existente, siempre se crea una versión nueva."""
    if body.activate:
        siblings = await db.execute(
            select(AIPrompt).where(AIPrompt.task_type == body.task_type, AIPrompt.is_active)
        )
        for sibling in siblings.scalars().all():
            sibling.is_active = False

    prompt = AIPrompt(
        task_type=body.task_type,
        version_name=body.version_name,
        system_prompt_text=body.system_prompt_text,
        is_active=body.activate,
        updated_by=current_user.id,
    )
    db.add(prompt)
    await db.commit()
    await db.refresh(prompt)
    return _serialize_prompt(prompt)


# ─── Configuración global del negocio ────────────────────────────────────────────


@router.get("/global-settings")
async def list_global_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(GlobalBusinessSetting).order_by(GlobalBusinessSetting.setting_key)
    )
    return {"settings": [_serialize_setting(s) for s in result.scalars().all()]}


class UpdateGlobalSettingRequest(BaseModel):
    setting_value: dict


@router.patch("/global-settings/{setting_key}")
async def update_global_setting(
    setting_key: str,
    body: UpdateGlobalSettingRequest,
    current_user: User = RequireAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upsert: crea la fila si `setting_key` no existe todavía (no hay seed de datos)."""
    result = await db.execute(
        select(GlobalBusinessSetting).where(GlobalBusinessSetting.setting_key == setting_key)
    )
    setting = result.scalar_one_or_none()

    if setting:
        setting.setting_value = body.setting_value
        setting.updated_by = current_user.id
    else:
        setting = GlobalBusinessSetting(
            setting_key=setting_key,
            setting_value=body.setting_value,
            updated_by=current_user.id,
        )
        db.add(setting)

    await db.commit()
    await db.refresh(setting)
    from src.infrastructure.cache.redis_client import redis_client
    if redis_client:
        await redis_client.delete(f"global_setting:{setting_key}")
    return _serialize_setting(setting)
