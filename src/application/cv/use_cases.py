from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.domain.hiring_process.rules import HiringProcessRules
from src.domain.hiring_process.state_machine import HiringProcessStateMachine
from src.infrastructure.db.models import (
    Candidate,
    CandidateStatus,
    ProcessCandidate,
    ProcessStatus,
    WhatsAppConsentStatus,
)
from src.infrastructure.db.repositories.candidate_repository import CandidateRepository
from src.infrastructure.db.repositories.process_repository import ProcessRepository
from src.infrastructure.storage import r2_client
from src.infrastructure.workers.tasks.parse_cv import parse_cv
from src.domain.shared.exceptions import BusinessRuleException, NotFoundException

_ALLOWED_EXTENSIONS = {
    ".pdf",
    ".docx", ".doc",
    ".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".bmp",
}
_CONTENT_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".bmp": "image/bmp",
}
_MAX_FILE_MB = 10


@dataclass
class UploadResult:
    candidate_id: uuid.UUID
    process_candidate_id: uuid.UUID
    filename: str
    task_id: str


class UploadCVsUseCase:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._candidate_repo = CandidateRepository(db)
        self._process_repo = ProcessRepository(db)

    async def execute(
        self,
        process_id: uuid.UUID,
        files: list[UploadFile],
        uploader_id: uuid.UUID,
    ) -> list[UploadResult]:
        process = await self._process_repo.find_by_id(process_id)
        if not process:
            raise NotFoundException("HiringProcess", str(process_id))

        HiringProcessRules.require_active_process(ProcessStatus(process.status))

        if not HiringProcessStateMachine.can_upload_cvs(ProcessStatus(process.status)):
            raise BusinessRuleException(
                f"El proceso en estado {process.status} no permite carga de CVs."
            )

        current_count = await self._candidate_repo.count_by_process(process_id)
        if current_count + len(files) > settings.cv_batch_limit:
            raise BusinessRuleException(
                f"Se superaría el límite de {settings.cv_batch_limit} CVs por proceso."
            )

        results: list[UploadResult] = []

        for file in files:
            if not file.filename:
                continue

            ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
            if ext not in _ALLOWED_EXTENSIONS:
                raise BusinessRuleException(
                    f"Formato no permitido: {file.filename}. "
                    f"Se aceptan: PDF, DOCX, JPG, PNG, WEBP."
                )

            content = await file.read()
            size_mb = len(content) / (1024 * 1024)
            if size_mb > _MAX_FILE_MB:
                raise BusinessRuleException(
                    f"El archivo {file.filename} supera el límite de {_MAX_FILE_MB}MB."
                )

            # Generar key único en R2
            candidate_id = uuid.uuid4()
            r2_key = f"cvs/{process_id}/{candidate_id}/{file.filename}"

            # Subir a R2 con el content-type correcto
            content_type = _CONTENT_TYPES.get(ext, "application/octet-stream")
            await r2_client.upload_file(r2_key, content, content_type)

            # Crear registro Candidate con placeholders
            filename_stem = file.filename.rsplit(".", 1)[0]
            candidate = Candidate(
                id=candidate_id,
                name="Procesando",
                last_name=filename_stem[:100],
                email=f"pending_{candidate_id}@placeholder.riwi",
                cv_file_url=r2_key,
            )
            await self._candidate_repo.save_candidate(candidate)

            # Crear ProcessCandidate
            pc = ProcessCandidate(
                process_id=process_id,
                candidate_id=candidate_id,
                status=CandidateStatus.LOADED.value,
                whatsapp_consent_status=WhatsAppConsentStatus.PENDING.value,
            )
            await self._candidate_repo.save_process_candidate(pc)

            # Actualizar estado del proceso si estaba en DRAFT
            if process.status == ProcessStatus.DRAFT.value:
                process.status = ProcessStatus.CVS_UPLOADED.value

            await self._db.flush()

            # Encolar tarea de parseo
            task = parse_cv.delay(
                str(candidate_id),
                str(pc.id),
                str(process_id),
            )

            results.append(UploadResult(
                candidate_id=candidate_id,
                process_candidate_id=pc.id,
                filename=file.filename,
                task_id=task.id,
            ))

        return results
