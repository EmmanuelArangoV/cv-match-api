from src.domain.shared.exceptions import UnauthorizedException
from src.infrastructure.auth.password import verify_password
from src.infrastructure.auth.refresh_tokens import (
    get_user_id_from_refresh,
    revoke_refresh_token,
    store_refresh_token,
)
from src.infrastructure.auth.tokens import create_access_token, create_refresh_token
from src.infrastructure.db.models import UserStatus
from src.infrastructure.db.repositories.user_repository import UserRepository


class LoginUseCase:
    def __init__(self, user_repo: UserRepository) -> None:
        self._repo = user_repo

    async def execute(self, email: str, password: str) -> dict:
        user = await self._repo.find_by_email(email)

        if not user or not verify_password(password, user.password_hash):
            raise UnauthorizedException("Credenciales inválidas")

        if user.status != UserStatus.ACTIVE.value:
            raise UnauthorizedException("Usuario suspendido")

        access_token = create_access_token(str(user.id), user.role)
        refresh_token = create_refresh_token()
        await store_refresh_token(refresh_token, str(user.id))

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "role": user.role,
        }


class RefreshTokenUseCase:
    def __init__(self, user_repo: UserRepository) -> None:
        self._repo = user_repo

    async def execute(self, refresh_token: str) -> dict:
        user_id = await get_user_id_from_refresh(refresh_token)

        if not user_id:
            raise UnauthorizedException("Refresh token inválido o expirado")

        user = await self._repo.find_by_id(user_id)

        if not user or user.status != UserStatus.ACTIVE.value:
            raise UnauthorizedException("Usuario no encontrado o suspendido")

        # Rotación: revoca el token usado y genera uno nuevo
        await revoke_refresh_token(refresh_token)
        new_access = create_access_token(str(user.id), user.role)
        new_refresh = create_refresh_token()
        await store_refresh_token(new_refresh, str(user.id))

        return {
            "access_token": new_access,
            "refresh_token": new_refresh,
            "token_type": "bearer",
            "role": user.role,
        }


class LogoutUseCase:
    async def execute(self, refresh_token: str) -> None:
        await revoke_refresh_token(refresh_token)
