from collections.abc import Callable

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.domain.shared.exceptions import ForbiddenException, UnauthorizedException
from src.infrastructure.auth.tokens import decode_access_token
from src.infrastructure.db.database import get_db
from src.infrastructure.db.models import User, UserRole, UserStatus
from src.infrastructure.db.repositories.user_repository import UserRepository
from sqlalchemy.ext.asyncio import AsyncSession

_bearer = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = decode_access_token(credentials.credentials)
    user = await UserRepository(db).find_by_id(payload["sub"])
    if not user or user.status != UserStatus.ACTIVE.value:
        raise UnauthorizedException("Usuario no encontrado o suspendido")
    return user


def require_role(*roles: UserRole) -> Callable:
    async def _checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in [r.value for r in roles]:
            raise ForbiddenException("Sin permisos para esta acción")
        return current_user
    return _checker


# Dependencias listas para usar en rutas
RequireAdmin = Depends(require_role(UserRole.ADMIN))
RequireRecruiter = Depends(require_role(UserRole.ADMIN, UserRole.RECRUITER, UserRole.TA_LEADER))
RequireTALeader = Depends(require_role(UserRole.ADMIN, UserRole.TA_LEADER))
