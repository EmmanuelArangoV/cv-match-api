"""Endpoints de debug — solo disponibles en APP_ENV=development."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.candidate.whatsapp_message_usecase import ProcessWhatsAppMessageUseCase
from src.config import settings
from src.infrastructure.db.database import get_db
from src.infrastructure.db.models import (
    Candidate,
    CandidateStatus,
    HiringProcess,
    ProcessCandidate,
    ProcessStatus,
    UserRole,
    UserStatus,
    WhatsAppConsentStatus,
    User,
)

router = APIRouter(prefix="/debug", tags=["Debug (dev only)"])


def _require_dev() -> None:
    if settings.app_env != "development":
        raise HTTPException(status_code=404, detail="Not found")


class SeedRequest(BaseModel):
    phone: str
    candidate_name: str = "Candidato Prueba"
    candidate_email: str = "test@riwi.io"
    job_title: str = "Desarrollador Backend"


class SimulateMessageRequest(BaseModel):
    from_phone: str
    message: str


@router.post("/seed-whatsapp-test")
async def seed_whatsapp_test(
    body: SeedRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_dev),
) -> dict:
    """
    Crea un recruiter de prueba, un HiringProcess y un Candidate con el teléfono dado,
    dejando el ProcessCandidate en estado PENDING de consentimiento.
    Úsalo para simular el flujo completo de WhatsApp sin necesitar la plantilla aprobada.
    """
    # Recruiter de prueba (reusable)
    recruiter_email = "recruiter-test@riwi.io"
    result = await db.execute(select(User).where(User.email == recruiter_email))
    recruiter = result.scalar_one_or_none()
    if not recruiter:
        import bcrypt as _bcrypt
        recruiter = User(
            id=uuid.uuid4(),
            name="Recruiter",
            last_name="Test",
            email=recruiter_email,
            password_hash=_bcrypt.hashpw(b"test1234", _bcrypt.gensalt()).decode(),
            role=UserRole.RECRUITER,
            status=UserStatus.ACTIVE,
        )
        db.add(recruiter)
        await db.flush()

    # HiringProcess
    process = HiringProcess(
        id=uuid.uuid4(),
        recruiter_id=recruiter.id,
        job_title=body.job_title,
        status=ProcessStatus.CVS_UPLOADED,
    )
    db.add(process)
    await db.flush()

    # Candidate
    name_parts = body.candidate_name.strip().split(" ", 1)
    candidate = Candidate(
        id=uuid.uuid4(),
        email=body.candidate_email,
        name=name_parts[0],
        last_name=name_parts[1] if len(name_parts) > 1 else "",
        phone=body.phone,
        status=CandidateStatus.MATCHED,
    )
    db.add(candidate)
    await db.flush()

    # ProcessCandidate con consentimiento PENDING
    pc = ProcessCandidate(
        id=uuid.uuid4(),
        process_id=process.id,
        candidate_id=candidate.id,
        whatsapp_consent_status=WhatsAppConsentStatus.PENDING,
        match_percentage=85.0,
    )
    db.add(pc)
    await db.commit()

    return {
        "ok": True,
        "process_id": str(process.id),
        "candidate_id": str(candidate.id),
        "process_candidate_id": str(pc.id),
        "phone_registered": body.phone,
        "next": f"Ahora simula un mensaje con POST /api/v1/debug/simulate-whatsapp-message",
    }


@router.post("/simulate-whatsapp-message")
async def simulate_whatsapp_message(
    body: SimulateMessageRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_dev),
) -> dict:
    """
    Simula que Meta envió un mensaje de WhatsApp de `from_phone`.
    Ejecuta el mismo use case que usa el webhook real.
    """
    use_case = ProcessWhatsAppMessageUseCase(db)
    await use_case.execute(from_phone=body.from_phone, message_text=body.message)
    return {"ok": True, "from": body.from_phone, "message": body.message}
