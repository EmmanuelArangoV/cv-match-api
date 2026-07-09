from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.auth.use_cases import LoginUseCase, LogoutUseCase, RefreshTokenUseCase
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


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> dict:
    result = await LoginUseCase(UserRepository(db)).execute(body.email, body.password)
    from src.infrastructure.db.audit import record_audit
    user = await UserRepository(db).find_by_email(body.email)
    if user:
        record_audit(db, user.id, "USER_LOGIN", "User", user.id)
        await db.commit()
    return result


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)) -> dict:
    return await RefreshTokenUseCase(UserRepository(db)).execute(body.refresh_token)


@router.post("/logout", status_code=204)
async def logout(body: RefreshRequest) -> None:
    await LogoutUseCase().execute(body.refresh_token)
