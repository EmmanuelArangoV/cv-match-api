import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import RequireAdmin, get_current_user, get_db
from src.application.auth.users_use_cases import (
    CreateUserUseCase,
    ListUsersUseCase,
    UpdateUserStatusUseCase,
    UpdateUserUseCase,
)
from src.infrastructure.db.models import User, UserRole, UserStatus
from src.infrastructure.db.repositories.user_repository import UserRepository

router = APIRouter(prefix="/users", tags=["Users"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class UserResponse(BaseModel):
    id: uuid.UUID
    name: str
    last_name: str
    email: str
    role: UserRole
    status: UserStatus
    created_at: str

    @classmethod
    def from_domain(cls, user: User) -> "UserResponse":
        return cls(
            id=user.id,
            name=user.name,
            last_name=user.last_name,
            email=user.email,
            role=user.role,
            status=user.status,
            created_at=user.created_at.isoformat(),
        )


class CreateUserRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8)
    role: UserRole


class UpdateUserRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = Field(None, min_length=1, max_length=100)
    email: EmailStr | None = None
    password: str | None = Field(None, min_length=8)
    role: UserRole | None = None


class UpdateUserStatusRequest(BaseModel):
    status: UserStatus


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[UserResponse])
async def list_users(
    current_user: User = RequireAdmin,
    db: AsyncSession = Depends(get_db),
) -> list[UserResponse]:
    repo = UserRepository(db)
    users = await ListUsersUseCase(repo).execute()
    return [UserResponse.from_domain(u) for u in users]


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    return UserResponse.from_domain(current_user)


@router.post("", status_code=201, response_model=UserResponse)
async def create_user(
    body: CreateUserRequest,
    current_user: User = RequireAdmin,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    repo = UserRepository(db)
    user = await CreateUserUseCase(repo).execute(body.model_dump())
    from src.infrastructure.db.audit import record_audit
    record_audit(db, current_user.id, "USER_MANAGEMENT", "User", user.id)
    await db.commit()
    await db.refresh(user)
    return UserResponse.from_domain(user)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    body: UpdateUserRequest,
    current_user: User = RequireAdmin,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    repo = UserRepository(db)
    update_data = {k: v for k, v in body.model_dump().items() if v is not None}
    user = await UpdateUserUseCase(repo).execute(user_id, update_data)
    from src.infrastructure.db.audit import record_audit
    record_audit(db, current_user.id, "USER_MANAGEMENT", "User", user.id)
    await db.commit()
    await db.refresh(user)
    return UserResponse.from_domain(user)


@router.patch("/{user_id}/status", response_model=UserResponse)
async def update_user_status(
    user_id: uuid.UUID,
    body: UpdateUserStatusRequest,
    current_user: User = RequireAdmin,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    repo = UserRepository(db)
    user = await UpdateUserStatusUseCase(repo).execute(user_id, body.status.value)
    from src.infrastructure.db.audit import record_audit
    record_audit(db, current_user.id, "USER_MANAGEMENT", "User", user.id)
    await db.commit()
    await db.refresh(user)
    return UserResponse.from_domain(user)
