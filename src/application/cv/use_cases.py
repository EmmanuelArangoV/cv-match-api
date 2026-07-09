from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.domain.hiring_process.rules import HiringProcessRules
from src.domain.hiring_process.state_machine import HiringProcessStateMachine
from src.domain.shared.exceptions import BusinessRuleException, NotFoundException
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

_ALLOWED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".doc",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".tiff",
    ".tif",
    ".bmp",
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
        import asyncio

        process = await self._process_repo.find_by_id(process_id)
        if not process:
            raise NotFoundException("HiringProcess", str(process_id))

        HiringProcessRules.require_active_process(ProcessStatus(process.status))

        if not HiringProcessStateMachine.can_upload_cvs(ProcessStatus(process.status)):
            raise BusinessRuleException(
                f"El proceso en estado {process.status} no permite carga de CVs."
            )

        # RB-010: Check budget
        from sqlalchemy import func, select

        from src.infrastructure.db.models import CostLog
        cost_query = select(func.sum(CostLog.estimated_cost)).where(CostLog.process_id == process_id)
        cost_result = await self._db.execute(cost_query)
        total_cost = cost_result.scalar() or 0.0
        HiringProcessRules.require_budget_available(total_cost, float(process.budget_max_usd))

        current_count = await self._candidate_repo.count_by_process(process_id)
        if current_count + len(files) > settings.cv_batch_limit:
            raise BusinessRuleException(
                f"Se superaría el límite de {settings.cv_batch_limit} CVs por proceso."
            )

        valid_files = []
        for file in files:
            if not file.filename:
                continue

            ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
            if ext not in _ALLOWED_EXTENSIONS:
                raise BusinessRuleException(
                    f"Formato no permitido: {file.filename}. Se aceptan: PDF, DOCX, JPG, PNG, WEBP."
                )

            content = await file.read()
            size_mb = len(content) / (1024 * 1024)
            if size_mb > settings.max_cv_file_size_mb:
                raise BusinessRuleException(
                    f"El archivo {file.filename} supera el límite de {settings.max_cv_file_size_mb}MB."
                )

            valid_files.append((file, ext, content))

        upload_tasks = []
        file_meta = []
        # Para deduplicar de forma síncrona/batch, pre-calculamos hashes
        for file, ext, content in valid_files:
            file_hash = hashlib.sha256(content).hexdigest()
            file_meta.append((file.filename, ext, content, file_hash))

        results: list[UploadResult] = []

        for filename, ext, content, file_hash in file_meta:
            existing_candidate = await self._candidate_repo.find_by_cv_file_hash(file_hash)

            if existing_candidate:
                # El CV ya existe. Verificamos si ya está en este proceso.
                existing_pc = await self._candidate_repo.find_process_candidate(
                    process_id, existing_candidate.id
                )
                if existing_pc:
                    results.append(
                        UploadResult(
                            candidate_id=existing_candidate.id,
                            process_candidate_id=existing_pc.id,
                            filename=filename,
                            task_id="already_exists",
                        )
                    )
                    continue

                # Crear nuevo ProcessCandidate vinculado al candidato existente
                pc = ProcessCandidate(
                    process_id=process_id,
                    candidate_id=existing_candidate.id,
                    status=CandidateStatus.MATCH_PENDING.value,
                    whatsapp_consent_status=WhatsAppConsentStatus.PENDING.value,
                )
                await self._candidate_repo.save_process_candidate(pc)

                if process.status == ProcessStatus.DRAFT.value:
                    process.status = ProcessStatus.CVS_UPLOADED.value
                # Commit antes de encolar: get_db() solo comitea al final del
                # request, y el worker de Celery lee con una conexion distinta
                # que no ve filas todavia sin comitear (causaba "not found").
                await self._db.commit()

                # Ejecutar match inmediatamente (ya tenemos la normalización)
                from src.infrastructure.workers.tasks.run_match import run_match

                task = run_match.delay(
                    process_candidate_id=str(pc.id),
                    process_id=str(process_id),
                )

                results.append(
                    UploadResult(
                        candidate_id=existing_candidate.id,
                        process_candidate_id=pc.id,
                        filename=filename,
                        task_id=task.id,
                    )
                )
            else:
                # Candidato nuevo
                candidate_id = uuid.uuid4()
                r2_key = f"cvs/{process_id}/{candidate_id}/{filename}"
                content_type = _CONTENT_TYPES.get(ext, "application/octet-stream")

                upload_tasks.append(r2_client.upload_file(r2_key, content, content_type))

                filename_stem = filename.rsplit(".", 1)[0]
                candidate = Candidate(
                    id=candidate_id,
                    name="Procesando",
                    last_name=filename_stem[:100],
                    email=f"pending_{candidate_id}@placeholder.riwi",
                    cv_file_url=r2_key,
                    cv_file_hash=file_hash,
                )
                await self._candidate_repo.save_candidate(candidate)

                pc = ProcessCandidate(
                    process_id=process_id,
                    candidate_id=candidate_id,
                    status=CandidateStatus.LOADED.value,
                    whatsapp_consent_status=WhatsAppConsentStatus.PENDING.value,
                )
                await self._candidate_repo.save_process_candidate(pc)

                if process.status == ProcessStatus.DRAFT.value:
                    process.status = ProcessStatus.CVS_UPLOADED.value

                # Commit antes de encolar: get_db() solo comitea al final del
                # request, y el worker de Celery lee con una conexion distinta
                # que no ve filas todavia sin comitear (causaba "not found").
                await self._db.commit()

                task = parse_cv.delay(
                    str(candidate_id),
                    str(pc.id),
                    str(process_id),
                )

                results.append(
                    UploadResult(
                        candidate_id=candidate_id,
                        process_candidate_id=pc.id,
                        filename=filename,
                        task_id=task.id,
                    )
                )

        if upload_tasks:
            await asyncio.gather(*upload_tasks)

        return results
