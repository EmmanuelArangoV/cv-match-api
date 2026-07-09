import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.infrastructure.db.models import (
    Candidate,
    ProcessCandidate,
)


class CandidateRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def find_candidate_by_id(self, candidate_id: uuid.UUID) -> Candidate | None:
        result = await self._db.execute(select(Candidate).where(Candidate.id == candidate_id))
        return result.scalar_one_or_none()

    async def find_by_email(self, email: str) -> Candidate | None:
        result = await self._db.execute(select(Candidate).where(Candidate.email == email))
        return result.scalar_one_or_none()

    async def find_by_cv_file_hash(self, file_hash: str) -> Candidate | None:
        result = await self._db.execute(
            select(Candidate).where(Candidate.cv_file_hash == file_hash)
        )
        return result.scalar_one_or_none()

    async def save_candidate(self, candidate: Candidate) -> Candidate:
        self._db.add(candidate)
        await self._db.flush()
        await self._db.refresh(candidate)
        return candidate

    async def save_process_candidate(self, pc: ProcessCandidate) -> ProcessCandidate:
        self._db.add(pc)
        await self._db.flush()
        await self._db.refresh(pc)
        return pc

    async def find_process_candidates(self, process_id: uuid.UUID) -> list[ProcessCandidate]:
        result = await self._db.execute(
            select(ProcessCandidate)
            .where(ProcessCandidate.process_id == process_id)
            .options(selectinload(ProcessCandidate.candidate))
            .order_by(ProcessCandidate.match_percentage.desc())
        )
        return list(result.scalars().all())

    async def find_process_candidate_by_id(self, pc_id: uuid.UUID) -> ProcessCandidate | None:
        result = await self._db.execute(
            select(ProcessCandidate)
            .where(ProcessCandidate.id == pc_id)
            .options(selectinload(ProcessCandidate.candidate))
        )
        return result.scalar_one_or_none()

    async def find_process_candidate(
        self, process_id: uuid.UUID, candidate_id: uuid.UUID
    ) -> ProcessCandidate | None:
        result = await self._db.execute(
            select(ProcessCandidate).where(
                ProcessCandidate.process_id == process_id,
                ProcessCandidate.candidate_id == candidate_id,
            )
        )
        return result.scalar_one_or_none()

    async def count_by_process(self, process_id: uuid.UUID) -> int:
        result = await self._db.execute(
            select(ProcessCandidate).where(ProcessCandidate.process_id == process_id)
        )
        return len(result.scalars().all())
