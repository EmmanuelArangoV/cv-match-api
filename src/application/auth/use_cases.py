from datetime import UTC, datetime, timedelta

from src.config import settings
from src.domain.shared.exceptions import UnauthorizedException
from src.infrastructure.auth.password import verify_password
from src.infrastructure.auth.refresh_tokens import (
    get_refresh_session,
    revoke_refresh_token,
    store_refresh_token,
)
from src.infrastructure.auth.tokens import create_access_token, create_refresh_token
from src.infrastructure.db.models import UserStatus
from src.infrastructure.db.repositories.user_repository import UserRepository


class LoginUseCase:
    def __init__(self, user_repo: UserRepository) -> None:
        self._repo = user_repo

    async def execute(self, email: str, password: str) -> dict[str, object]:
        user = await self._repo.find_by_email(email)

        if not user or not user.password_hash or not verify_password(password, user.password_hash):
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

    async def execute(self, refresh_token: str) -> dict[str, object]:
        refresh_session = await get_refresh_session(refresh_token)

        if not refresh_session:
            raise UnauthorizedException("Refresh token inválido o expirado")

        now = datetime.now(UTC)
        absolute_expires_at = refresh_session.absolute_expires_at
        if absolute_expires_at is not None and absolute_expires_at <= int(now.timestamp()):
            await revoke_refresh_token(refresh_token)
            raise UnauthorizedException("Refresh token inválido o expirado")

        user = await self._repo.find_by_id(refresh_session.user_id)

        if not user or user.status != UserStatus.ACTIVE.value:
            raise UnauthorizedException("Usuario no encontrado o suspendido")

        # Rotación: revoca el token usado y genera uno nuevo
        await revoke_refresh_token(refresh_token)
        local_deadline = None
        if absolute_expires_at is not None:
            local_deadline = min(
                datetime.fromtimestamp(absolute_expires_at, UTC),
                now + timedelta(minutes=settings.access_token_expire_minutes),
            )
        new_access = create_access_token(str(user.id), user.role, expires_at=local_deadline)
        new_refresh = create_refresh_token()
        await store_refresh_token(
            new_refresh,
            str(user.id),
            absolute_expires_at=absolute_expires_at,
        )

        result: dict[str, object] = {
            "access_token": new_access,
            "refresh_token": new_refresh,
            "token_type": "bearer",
            "role": user.role,
        }
        if absolute_expires_at is not None and local_deadline is not None:
            result["expires_in"] = max(1, int((local_deadline - now).total_seconds()))
            result["session_expires_in"] = max(
                1, absolute_expires_at - int(now.timestamp())
            )
        return result


class LogoutUseCase:
    async def execute(self, refresh_token: str) -> None:
        await revoke_refresh_token(refresh_token)
