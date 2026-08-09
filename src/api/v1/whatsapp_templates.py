from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import RequireAdmin, RequireRecruiter
from src.domain.shared.exceptions import BusinessRuleException, ConflictException, NotFoundException
from src.infrastructure.db.audit import record_audit
from src.infrastructure.db.database import get_db
from src.infrastructure.db.models import User, WhatsAppTemplate, WhatsAppTemplateStatus
from src.infrastructure.messaging.whatsapp_client import (
    SUPPORTED_TEMPLATE_BINDINGS,
    template_bindings_are_valid,
    whatsapp_client,
)

admin_router = APIRouter(prefix="/ai-config/whatsapp-templates", tags=["AI Config"])
router = APIRouter(prefix="/whatsapp-templates", tags=["WhatsApp Templates"])

_PLACEHOLDER_RE = re.compile(r"\{\{(\d+)\}\}")
_NAME_RE = re.compile(r"^[a-z0-9_]+$")


def _binding_positions(body_text: str) -> list[int]:
    return sorted({int(value) for value in _PLACEHOLDER_RE.findall(body_text)})


def _bindings_complete(template: WhatsAppTemplate) -> bool:
    return template_bindings_are_valid(
        template.components or [], template.variable_bindings or {}
    )


def serialize_template(template: WhatsAppTemplate) -> dict[str, Any]:
    selectable = (
        str(template.status) == WhatsAppTemplateStatus.APPROVED.value
        and template.is_enabled
        and _bindings_complete(template)
    )
    return {
        "id": str(template.id),
        "meta_template_id": template.meta_template_id,
        "name": template.name,
        "language": template.language,
        "category": template.category,
        "status": str(template.status),
        "components": template.components or [],
        "variable_bindings": template.variable_bindings or {},
        "rejection_reason": template.rejection_reason,
        "is_enabled": template.is_enabled,
        "is_default": template.is_default,
        "is_selectable": selectable,
        "last_synced_at": (
            template.last_synced_at.isoformat() if template.last_synced_at else None
        ),
        "created_at": template.created_at.isoformat(),
        "updated_at": template.updated_at.isoformat(),
    }


class CreateWhatsAppTemplateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=512)
    language: str = Field(default="es_CO", min_length=2, max_length=20)
    body_text: str = Field(..., min_length=10, max_length=1024)
    header_text: str | None = Field(default=None, max_length=60)
    footer_text: str | None = Field(default=None, max_length=60)
    accept_button_text: str = Field(default="Sí, acepto", min_length=1, max_length=25)
    reject_button_text: str = Field(default="No, gracias", min_length=1, max_length=25)
    variable_bindings: dict[str, str] = Field(default_factory=dict)
    variable_examples: dict[str, str] = Field(default_factory=dict)


def _normalize_status(value: Any) -> WhatsAppTemplateStatus:
    raw_status = str(value or WhatsAppTemplateStatus.UNKNOWN.value).upper()
    try:
        return WhatsAppTemplateStatus(raw_status)
    except ValueError:
        return WhatsAppTemplateStatus.UNKNOWN


def _build_meta_payload(
    body: CreateWhatsAppTemplateRequest,
) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    name = body.name.strip()
    if not _NAME_RE.fullmatch(name):
        raise BusinessRuleException(
            "El nombre de Meta solo puede contener minúsculas, números y guiones bajos."
        )
    positions = _binding_positions(body.body_text)
    expected = list(range(1, len(positions) + 1))
    if positions != expected:
        raise BusinessRuleException("Las variables del body deben ser consecutivas desde {{1}}.")
    normalized_bindings: dict[str, str] = {}
    examples: list[str] = []
    for position in positions:
        key = body.variable_bindings.get(str(position), "")
        if key not in SUPPORTED_TEMPLATE_BINDINGS:
            raise BusinessRuleException(
                f"Asigna la variable {{{{{position}}}}} a un dato soportado."
            )
        example = body.variable_examples.get(str(position), "").strip()
        if not example:
            raise BusinessRuleException(
                f"Meta exige un valor de ejemplo para {{{{{position}}}}}."
            )
        normalized_bindings[str(position)] = key
        examples.append(example)

    components: list[dict[str, Any]] = []
    if body.header_text and body.header_text.strip():
        components.append(
            {"type": "HEADER", "format": "TEXT", "text": body.header_text.strip()}
        )
    body_component: dict[str, Any] = {"type": "BODY", "text": body.body_text.strip()}
    if examples:
        body_component["example"] = {"body_text": [examples]}
    components.append(body_component)
    if body.footer_text and body.footer_text.strip():
        components.append({"type": "FOOTER", "text": body.footer_text.strip()})
    components.append(
        {
            "type": "BUTTONS",
            "buttons": [
                {"type": "QUICK_REPLY", "text": body.accept_button_text.strip()},
                {"type": "QUICK_REPLY", "text": body.reject_button_text.strip()},
            ],
        }
    )
    return (
        {
            "name": name,
            "language": body.language.strip(),
            "category": "UTILITY",
            "components": components,
        },
        {"BODY": normalized_bindings},
    )


@admin_router.get("")
async def list_admin_templates(
    current_user: User = RequireAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows = (
        (await db.execute(select(WhatsAppTemplate).order_by(WhatsAppTemplate.created_at.desc())))
        .scalars()
        .all()
    )
    return {"templates": [serialize_template(row) for row in rows]}


@router.get("")
async def list_selectable_templates(
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows = (
        (
            await db.execute(
                select(WhatsAppTemplate)
                .where(
                    WhatsAppTemplate.status == WhatsAppTemplateStatus.APPROVED.value,
                    WhatsAppTemplate.is_enabled.is_(True),
                )
                .order_by(WhatsAppTemplate.is_default.desc(), WhatsAppTemplate.name)
            )
        )
        .scalars()
        .all()
    )
    return {
        "templates": [serialize_template(row) for row in rows if _bindings_complete(row)]
    }


@admin_router.post("", status_code=201)
async def create_template(
    body: CreateWhatsAppTemplateRequest,
    current_user: User = RequireAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    payload, bindings = _build_meta_payload(body)
    existing = await db.scalar(
        select(WhatsAppTemplate).where(
            WhatsAppTemplate.name == payload["name"],
            WhatsAppTemplate.language == payload["language"],
        )
    )
    if existing:
        raise ConflictException(
            "Ya existe una plantilla con ese nombre e idioma. "
            "Crea una nueva versión con otro nombre."
        )

    template = WhatsAppTemplate(
        name=payload["name"],
        language=payload["language"],
        category="UTILITY",
        status=WhatsAppTemplateStatus.SUBMITTING,
        components=payload["components"],
        variable_bindings=bindings,
        is_enabled=False,
        is_default=False,
        created_by=current_user.id,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    try:
        remote = await whatsapp_client.create_template(payload)
    except Exception as exc:
        template.status = WhatsAppTemplateStatus.SUBMISSION_FAILED
        template.rejection_reason = str(exc)[:2000]
        template.last_synced_at = datetime.now(UTC)
        await db.commit()
        raise

    template.meta_template_id = str(remote.get("id") or "") or None
    template.status = _normalize_status(
        remote.get("status") or WhatsAppTemplateStatus.PENDING.value
    )
    template.category = str(remote.get("category") or "UTILITY").upper()
    template.last_synced_at = datetime.now(UTC)
    record_audit(
        db,
        current_user.id,
        "WHATSAPP_TEMPLATE_SUBMITTED",
        "WhatsAppTemplate",
        template.id,
        new_value={"name": template.name, "language": template.language},
    )
    await db.commit()
    await db.refresh(template)
    return serialize_template(template)


@admin_router.post("/sync")
async def sync_templates(
    current_user: User = RequireAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    remote_rows = await whatsapp_client.list_templates()
    now = datetime.now(UTC)
    created = 0
    updated = 0
    for remote in remote_rows:
        remote_id = str(remote.get("id") or "") or None
        name = str(remote.get("name") or "")
        language = str(remote.get("language") or "")
        if not name or not language:
            continue
        conditions: list[Any] = [
            (WhatsAppTemplate.name == name) & (WhatsAppTemplate.language == language)
        ]
        if remote_id:
            conditions.append(WhatsAppTemplate.meta_template_id == remote_id)
        template = await db.scalar(select(WhatsAppTemplate).where(or_(*conditions)))
        if not template:
            template = WhatsAppTemplate(
                meta_template_id=remote_id,
                name=name,
                language=language,
                category=str(remote.get("category") or "UTILITY").upper(),
                status=_normalize_status(remote.get("status")),
                components=remote.get("components") or [],
                variable_bindings={},
                is_enabled=False,
                is_default=False,
                created_by=current_user.id,
            )
            db.add(template)
            created += 1
        else:
            template.meta_template_id = remote_id or template.meta_template_id
            template.category = str(remote.get("category") or template.category).upper()
            template.status = _normalize_status(remote.get("status"))
            template.components = remote.get("components") or template.components
            template.rejection_reason = remote.get("rejected_reason")
            updated += 1
        template.last_synced_at = now
        if template.status != WhatsAppTemplateStatus.APPROVED.value:
            template.is_enabled = False
            template.is_default = False
    record_audit(
        db,
        current_user.id,
        "WHATSAPP_TEMPLATES_SYNCED",
        "WhatsAppTemplate",
        None,
        new_value={"remote": len(remote_rows), "created": created, "updated": updated},
    )
    await db.commit()
    return {"remote": len(remote_rows), "created": created, "updated": updated}


class UpdateWhatsAppTemplateRequest(BaseModel):
    variable_bindings: dict[str, str] | None = None
    is_enabled: bool | None = None
    is_default: bool | None = None


@admin_router.patch("/{template_id}")
async def update_template(
    template_id: uuid.UUID,
    body: UpdateWhatsAppTemplateRequest,
    current_user: User = RequireAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    template = await db.get(WhatsAppTemplate, template_id)
    if not template:
        raise NotFoundException("Plantilla de WhatsApp no encontrada")
    if body.variable_bindings is not None:
        template.variable_bindings = {"BODY": body.variable_bindings}
    wants_selectable = body.is_enabled is True or body.is_default is True
    if wants_selectable and str(template.status) != WhatsAppTemplateStatus.APPROVED.value:
        raise BusinessRuleException(
            "Solo una plantilla APPROVED puede habilitarse o ser predeterminada."
        )
    if wants_selectable and not _bindings_complete(template):
        raise BusinessRuleException(
            "Completa el mapeo de todas las variables antes de habilitarla."
        )
    if body.is_default is True:
        siblings = await db.execute(select(WhatsAppTemplate).where(WhatsAppTemplate.is_default))
        for sibling in siblings.scalars().all():
            sibling.is_default = False
        template.is_default = True
        template.is_enabled = True
    elif body.is_default is False:
        template.is_default = False
    if body.is_enabled is not None:
        if template.is_default and not body.is_enabled:
            raise BusinessRuleException(
                "Asigna otra plantilla predeterminada antes de deshabilitar la actual."
            )
        template.is_enabled = body.is_enabled
    record_audit(
        db,
        current_user.id,
        "WHATSAPP_TEMPLATE_CONFIGURED",
        "WhatsAppTemplate",
        template.id,
        new_value={"is_enabled": template.is_enabled, "is_default": template.is_default},
    )
    await db.commit()
    await db.refresh(template)
    return serialize_template(template)
