import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from src.application.auth.orbita_use_case import OrbitaLoginUseCase
from src.domain.shared.exceptions import ConflictException, ForbiddenException
from src.infrastructure.auth.orbita_sso import OrbitaIdentity, OrbitaTokenResponse


class FakeUserRepository:
    def __init__(self, *, linked_user=None, email_owner=None):
        self.linked_user = linked_user
        self.email_owner = email_owner
        self.saved_user = None

    async def find_by_orbita_user_id(self, _orbita_user_id):
        return self.linked_user

    async def find_by_email(self, _email):
        return self.email_owner

    async def save(self, user):
        if user.id is None:
            user.id = uuid.uuid4()
        self.saved_user = user
        return user


def orbita_identity(*, roles=("recruiter",), expires_in=1200):
    return OrbitaIdentity(
        subject=str(uuid.uuid4()),
        email="Recruiter@Riwi.io",
        name="Ada Lovelace",
        roles=roles,
        token_id="orbita-token-id",
        expires_at=int(datetime.now(UTC).timestamp()) + expires_in,
    )


@pytest.mark.asyncio
async def test_orbita_login_provisions_user_and_caps_refresh_session(monkeypatch):
    identity = orbita_identity(roles=("recruiter", "admin"))
    client = AsyncMock()
    client.exchange_code.return_value = (
        OrbitaTokenResponse(access_token="orbita-jwt", expires_in=1800),
        identity,
    )
    repo = FakeUserRepository()
    stored_refresh = AsyncMock()

    monkeypatch.setattr(
        "src.application.auth.orbita_use_case.create_access_token",
        lambda *_args, **_kwargs: "match-access",
    )
    monkeypatch.setattr(
        "src.application.auth.orbita_use_case.create_refresh_token",
        lambda: "match-refresh",
    )
    monkeypatch.setattr(
        "src.application.auth.orbita_use_case.store_refresh_token",
        stored_refresh,
    )

    result, user = await OrbitaLoginUseCase(repo, client).execute("one-time-code")

    assert result["access_token"] == "match-access"
    assert result["role"] == "ADMIN"
    assert user.email == "recruiter@riwi.io"
    assert user.name == "Ada"
    assert user.last_name == "Lovelace"
    assert user.password_hash is None
    assert user.orbita_user_id == uuid.UUID(identity.subject)
    stored_refresh.assert_awaited_once_with(
        "match-refresh",
        str(user.id),
        absolute_expires_at=identity.expires_at,
    )


@pytest.mark.asyncio
async def test_orbita_login_refuses_implicit_link_to_local_email():
    client = AsyncMock()
    client.exchange_code.return_value = (
        OrbitaTokenResponse(access_token="orbita-jwt", expires_in=1200),
        orbita_identity(),
    )
    local_owner = type("LocalUser", (), {"id": uuid.uuid4()})()
    repo = FakeUserRepository(email_owner=local_owner)

    with pytest.raises(ConflictException, match="vinculación"):
        await OrbitaLoginUseCase(repo, client).execute("one-time-code")


def test_orbita_roles_fail_closed_for_unknown_key():
    with pytest.raises(ForbiddenException, match="no reconocidos"):
        OrbitaLoginUseCase._resolve_role(("recruiter", "unexpected_role"))
