import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from src.application.auth.use_cases import LoginUseCase, RefreshTokenUseCase
from src.domain.shared.exceptions import UnauthorizedException
from src.infrastructure.auth.refresh_tokens import RefreshSession


class MockUser:
    def __init__(self, email, password_hash, status):
        self.id = uuid.uuid4()
        self.email = email
        self.password_hash = password_hash
        self.status = status
        self.role = "RECRUITER"


@pytest.mark.asyncio
async def test_login_success():
    mock_repo = AsyncMock()

    test_user = MockUser(email="test@example.com", password_hash="hashed", status="ACTIVE")

    with (
        patch("src.application.auth.use_cases.UserRepository", return_value=mock_repo),
        patch("src.application.auth.use_cases.verify_password", return_value=True),
        patch("src.application.auth.use_cases.create_access_token", return_value="token123"),
        patch("src.application.auth.use_cases.create_refresh_token", return_value="refresh123"),
    ):
        mock_repo.find_by_email = AsyncMock(return_value=test_user)

        use_case = LoginUseCase(mock_repo)
        result = await use_case.execute("test@example.com", "password")

        assert result["access_token"] == "token123"
        assert result["refresh_token"] == "refresh123"


@pytest.mark.asyncio
async def test_login_invalid_password():
    mock_repo = AsyncMock()

    test_user = MockUser(email="test@example.com", password_hash="hashed", status="ACTIVE")

    with (
        patch("src.application.auth.use_cases.UserRepository", return_value=mock_repo),
        patch("src.application.auth.use_cases.verify_password", return_value=False),
    ):
        mock_repo.find_by_email = AsyncMock(return_value=test_user)

        use_case = LoginUseCase(mock_repo)
        with pytest.raises(UnauthorizedException):
            await use_case.execute("test@example.com", "wrong_password")


@pytest.mark.asyncio
async def test_local_login_rejects_sso_only_user_without_password_hash():
    mock_repo = AsyncMock()
    mock_repo.find_by_email.return_value = MockUser(
        email="sso@example.com",
        password_hash=None,
        status="ACTIVE",
    )

    use_case = LoginUseCase(mock_repo)
    with pytest.raises(UnauthorizedException):
        await use_case.execute("sso@example.com", "any-password")


@pytest.mark.asyncio
async def test_refresh_preserves_orbita_absolute_expiration():
    mock_repo = AsyncMock()
    mock_repo.find_by_id.return_value = MockUser(
        email="sso@example.com",
        password_hash=None,
        status="ACTIVE",
    )
    absolute_expiration = int(datetime.now(UTC).timestamp()) + 120

    with (
        patch(
            "src.application.auth.use_cases.get_refresh_session",
            AsyncMock(
                return_value=RefreshSession(
                    user_id=str(mock_repo.find_by_id.return_value.id),
                    absolute_expires_at=absolute_expiration,
                )
            ),
        ),
        patch("src.application.auth.use_cases.revoke_refresh_token", AsyncMock()),
        patch("src.application.auth.use_cases.store_refresh_token", AsyncMock()) as store,
        patch("src.application.auth.use_cases.create_access_token", return_value="access"),
        patch("src.application.auth.use_cases.create_refresh_token", return_value="refresh"),
    ):
        result = await RefreshTokenUseCase(mock_repo).execute("previous-refresh")

    assert 1 <= result["expires_in"] <= 120
    assert 1 <= result["session_expires_in"] <= 120
    store.assert_awaited_once_with(
        "refresh",
        str(mock_repo.find_by_id.return_value.id),
        absolute_expires_at=absolute_expiration,
    )
