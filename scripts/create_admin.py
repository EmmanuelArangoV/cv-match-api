import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.infrastructure.auth.password import hash_password
from src.infrastructure.db.database import AsyncSessionFactory
from src.infrastructure.db.models import User, UserRole, UserStatus
from src.infrastructure.db.repositories.user_repository import UserRepository


async def main() -> None:
    print("=== Crear usuario Admin ===\n")
    name = input("Nombre: ").strip()
    last_name = input("Apellido: ").strip()
    email = input("Email: ").strip().lower()
    password = getpass.getpass("Contraseña: ")

    if not all([name, last_name, email, password]):
        print("Todos los campos son obligatorios.")
        sys.exit(1)

    if len(password) < 8:
        print("La contraseña debe tener al menos 8 caracteres.")
        sys.exit(1)

    async with AsyncSessionFactory() as db:
        repo = UserRepository(db)

        if await repo.email_exists(email):
            print(f"Ya existe un usuario con el email {email}.")
            sys.exit(1)

        user = User(
            name=name,
            last_name=last_name,
            email=email,
            password_hash=hash_password(password),
            role=UserRole.ADMIN.value,
            status=UserStatus.ACTIVE.value,
        )
        await repo.save(user)
        await db.commit()

    print(f"\nAdmin creado exitosamente: {email}")


if __name__ == "__main__":
    asyncio.run(main())
