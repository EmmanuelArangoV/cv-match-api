import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.db.models import User


class UserRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def find_by_email(self, email: str) -> User | None:
        result = await self._db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def find_by_id(self, user_id: uuid.UUID | str) -> User | None:
        result = await self._db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def find_all(self) -> list[User]:
        result = await self._db.execute(select(User).order_by(User.created_at.desc()))
        return list(result.scalars().all())

    async def save(self, user: User) -> User:
        self._db.add(user)
        await self._db.flush()
        await self._db.refresh(user)
        return user

    async def email_exists(self, email: str) -> bool:
        result = await self._db.execute(select(User.id).where(User.email == email))
        return result.scalar_one_or_none() is not None
