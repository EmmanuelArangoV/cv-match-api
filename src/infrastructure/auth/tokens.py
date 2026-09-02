import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from jwt import InvalidTokenError

from src.config import settings
from src.domain.shared.exceptions import UnauthorizedException

_ALGORITHM = "HS256"
_REFRESH_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 días


def create_access_token(user_id: str, role: str, *, expires_at: datetime | None = None) -> str:
    expire = expires_at or datetime.now(UTC) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {"sub": user_id, "role": role, "exp": expire}
    encoded = jwt.encode(payload, settings.app_secret_key, algorithm=_ALGORITHM)
    if not isinstance(encoded, str):
        raise UnauthorizedException("No se pudo crear el token")
    return encoded


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.app_secret_key, algorithms=[_ALGORITHM])
        if not isinstance(payload, dict):
            raise UnauthorizedException("Token inválido o expirado")
        return payload
    except InvalidTokenError:
        raise UnauthorizedException("Token inválido o expirado")


def create_refresh_token() -> str:
    return str(uuid.uuid4())


def get_refresh_ttl() -> int:
    return _REFRESH_TTL_SECONDS
