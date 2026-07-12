import uuid

from src.domain.shared.exceptions import BusinessRuleException, ConflictException, NotFoundException
from src.infrastructure.auth.password import hash_password
from src.infrastructure.db.models import User, UserStatus
from src.infrastructure.db.repositories.user_repository import UserRepository


class ListUsersUseCase:
    def __init__(self, user_repo: UserRepository) -> None:
        self._repo = user_repo

    async def execute(self) -> list[User]:
        return await self._repo.find_all()


class CreateUserUseCase:
    def __init__(self, user_repo: UserRepository) -> None:
        self._repo = user_repo

    async def execute(self, user_data: dict) -> User:
        if await self._repo.email_exists(user_data["email"]):
            raise ConflictException("El correo ya está registrado")

        user = User(
            name=user_data["name"],
            last_name=user_data["last_name"],
            email=user_data["email"],
            password_hash=hash_password(user_data["password"]),
            role=user_data["role"],
            status=UserStatus.ACTIVE.value,
        )
        return await self._repo.save(user)


class UpdateUserUseCase:
    def __init__(self, user_repo: UserRepository) -> None:
        self._repo = user_repo

    async def execute(self, user_id: uuid.UUID, user_data: dict) -> User:
        user = await self._repo.find_by_id(user_id)
        if not user:
            raise NotFoundException("User no encontrado")

        if "email" in user_data and user_data["email"] != user.email:
            if await self._repo.email_exists(user_data["email"]):
                raise ConflictException("El correo ya está registrado")
            user.email = user_data["email"]

        if "name" in user_data:
            user.name = user_data["name"]
        if "last_name" in user_data:
            user.last_name = user_data["last_name"]
        if "role" in user_data:
            user.role = user_data["role"]
        if "password" in user_data and user_data["password"]:
            user.password_hash = hash_password(user_data["password"])

        return await self._repo.save(user)


class UpdateUserStatusUseCase:
    def __init__(self, user_repo: UserRepository) -> None:
        self._repo = user_repo

    async def execute(self, user_id: uuid.UUID, status: str) -> User:
        user = await self._repo.find_by_id(user_id)
        if not user:
            raise NotFoundException("User no encontrado")

        if status not in [s.value for s in UserStatus]:
            raise BusinessRuleException(f"Estado {status} no válido")

        user.status = status
        return await self._repo.save(user)


class DeleteUserUseCase:
    def __init__(self, user_repo: UserRepository) -> None:
        self._repo = user_repo

    async def execute(self, user_id: uuid.UUID) -> None:
        user = await self._repo.find_by_id(user_id)
        if not user:
            raise NotFoundException("User no encontrado")
        await self._repo.delete(user)

