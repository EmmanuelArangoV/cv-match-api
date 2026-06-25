"""Script para crear un usuario recruiter para pruebas del nuevo front."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import bcrypt
from src.infrastructure.db.database import AsyncSessionFactory
from src.infrastructure.db.models import User, UserRole, UserStatus
from src.infrastructure.db.repositories.user_repository import UserRepository


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


async def main() -> None:
    email = "recruiter@riwi.io"
    password = "riwi2026"
    name = "Recruiter"
    last_name = "RIWI"

    async with AsyncSessionFactory() as db:
        repo = UserRepository(db)

        if await repo.email_exists(email):
            print(f"Ya existe: {email}")
            print(f"  Email:    {email}")
            print(f"  Password: {password}")
            return

        user = User(
            name=name,
            last_name=last_name,
            email=email,
            password_hash=hash_password(password),
            role=UserRole.RECRUITER.value,
            status=UserStatus.ACTIVE.value,
        )
        await repo.save(user)
        await db.commit()

    print(f"\nRecruiter creado exitosamente:")
    print(f"  Email:    {email}")
    print(f"  Password: {password}")
    print(f"  Role:     RECRUITER")


if __name__ == "__main__":
    asyncio.run(main())
