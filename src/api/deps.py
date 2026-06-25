from collections.abc import Callable

from fastapi import Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.domain.shared.exceptions import ForbiddenException, UnauthorizedException
from src.infrastructure.auth.tokens import decode_access_token
from src.infrastructure.db.database import get_db
from src.infrastructure.db.models import User, UserRole, UserStatus
from src.infrastructure.db.repositories.user_repository import UserRepository
from sqlalchemy.ext.asyncio import AsyncSession

_bearer = HTTPBearer()
_bearer_optional = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = decode_access_token(credentials.credentials)
    user = await UserRepository(db).find_by_id(payload["sub"])
    if not user or user.status != UserStatus.ACTIVE.value:
        raise UnauthorizedException("Usuario no encontrado o suspendido")
    return user


async def get_current_user_with_query(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_optional),
    token: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    token_str = None
    if credentials:
        token_str = credentials.credentials
    elif token:
        token_str = token

    if not token_str:
        raise UnauthorizedException("No se proporcionó token de autenticación")

    payload = decode_access_token(token_str)
    user = await UserRepository(db).find_by_id(payload["sub"])
    if not user or user.status != UserStatus.ACTIVE.value:
        raise UnauthorizedException("Usuario no encontrado o suspendido")
    return user


def require_role(roles: list[UserRole]) -> Callable:
    async def _checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in [r.value for r in roles]:
            raise ForbiddenException("Sin permisos para esta acción")
        return current_user
    return _checker


def require_role_with_query(roles: list[UserRole]) -> Callable:
    async def _checker(current_user: User = Depends(get_current_user_with_query)) -> User:
        if current_user.role not in [r.value for r in roles]:
            raise ForbiddenException("Sin permisos para esta acción")
        return current_user
    return _checker


# Dependencias listas para usar en rutas
RequireAdmin = Depends(require_role([UserRole.ADMIN]))
RequireRecruiter = Depends(require_role([UserRole.ADMIN, UserRole.RECRUITER, UserRole.TA_LEADER]))
RequireTALeader = Depends(require_role([UserRole.ADMIN, UserRole.TA_LEADER]))

RequireRecruiterWithQuery = Depends(require_role_with_query([UserRole.ADMIN, UserRole.RECRUITER, UserRole.TA_LEADER]))
RequireTALeaderWithQuery = Depends(require_role_with_query([UserRole.ADMIN, UserRole.TA_LEADER]))
