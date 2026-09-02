from functools import lru_cache

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.auth.orbita_use_case import OrbitaLoginUseCase
from src.application.auth.use_cases import LoginUseCase, LogoutUseCase, RefreshTokenUseCase
from src.config import settings
from src.domain.shared.exceptions import ServiceUnavailableException
from src.infrastructure.auth.orbita_sso import (
    OrbitaSsoClient,
    OrbitaSsoConfig,
    OrbitaSsoConfigurationError,
    OrbitaSsoUnavailableError,
)
from src.infrastructure.db.database import get_db
from src.infrastructure.db.repositories.user_repository import UserRepository

router = APIRouter(prefix="/auth", tags=["Auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    role: str


class RefreshTokenResponse(TokenResponse):
    expires_in: int | None = None
    session_expires_in: int | None = None


class OrbitaAuthorizeUrlResponse(BaseModel):
    authorization_url: str


class OrbitaExchangeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=2048)


class OrbitaSessionResponse(TokenResponse):
    expires_in: int
    session_expires_in: int


@lru_cache(maxsize=1)
def get_orbita_sso_client() -> OrbitaSsoClient:
    return OrbitaSsoClient(
        OrbitaSsoConfig(
            base_url=settings.orbita_sso_base_url,
            client_id=settings.orbita_sso_client_id,
            client_secret=settings.orbita_sso_client_secret,
            redirect_uri=settings.orbita_sso_redirect_uri,
            require_https=settings.app_env not in {"development", "test"},
        )
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> dict:
    result = await LoginUseCase(UserRepository(db)).execute(body.email, body.password)
    from src.infrastructure.db.audit import record_audit

    user = await UserRepository(db).find_by_email(body.email)
    if user:
        record_audit(db, user.id, "USER_LOGIN", "User", user.id)
        await db.commit()
    return result


@router.post(
    "/refresh",
    response_model=RefreshTokenResponse,
    response_model_exclude_none=True,
)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)) -> dict:
    return await RefreshTokenUseCase(UserRepository(db)).execute(body.refresh_token)


@router.post("/logout", status_code=204)
async def logout(body: RefreshRequest) -> None:
    await LogoutUseCase().execute(body.refresh_token)


@router.get("/orbita/authorize-url", response_model=OrbitaAuthorizeUrlResponse)
async def orbita_authorize_url(
    state: str = Query(min_length=16, max_length=512),
) -> OrbitaAuthorizeUrlResponse:
    try:
        url = await get_orbita_sso_client().authorization_url(state)
    except OrbitaSsoConfigurationError as exc:
        raise ServiceUnavailableException("El SSO de Órbita no está configurado") from exc
    except OrbitaSsoUnavailableError as exc:
        raise ServiceUnavailableException("Órbita no está disponible temporalmente") from exc
    return OrbitaAuthorizeUrlResponse(authorization_url=url)


@router.post("/orbita/exchange", response_model=OrbitaSessionResponse)
async def orbita_exchange(
    body: OrbitaExchangeRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    result, user = await OrbitaLoginUseCase(
        UserRepository(db), get_orbita_sso_client()
    ).execute(body.code)
    from src.infrastructure.db.audit import record_audit

    record_audit(db, user.id, "USER_LOGIN_ORBITA", "User", user.id)
    await db.commit()
    return result
