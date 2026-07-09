import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.db.models import HiringProcess, ProcessStatus


class ProcessRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def find_by_id(self, process_id: uuid.UUID) -> HiringProcess | None:
        result = await self._db.execute(select(HiringProcess).where(HiringProcess.id == process_id))
        return result.scalar_one_or_none()

    async def save(self, process: HiringProcess) -> HiringProcess:
        self._db.add(process)
        await self._db.flush()
        await self._db.refresh(process)
        return process

    async def update_status(self, process_id: uuid.UUID, status: ProcessStatus) -> None:
        process = await self.find_by_id(process_id)
        if process:
            process.status = status.value
            await self._db.flush()
