import pytest
from unittest.mock import AsyncMock, patch
from src.application.auth.use_cases import LoginUseCase
from src.domain.shared.exceptions import UnauthorizedException
import uuid

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
    
    test_user = MockUser(
        email="test@example.com",
        password_hash="hashed",
        status="ACTIVE"
    )
    
    with patch("src.application.auth.use_cases.UserRepository", return_value=mock_repo), \
         patch("src.application.auth.use_cases.verify_password", return_value=True), \
         patch("src.application.auth.use_cases.create_access_token", return_value="token123"), \
         patch("src.application.auth.use_cases.create_refresh_token", return_value="refresh123"):
        
        mock_repo.find_by_email = AsyncMock(return_value=test_user)
        
        use_case = LoginUseCase(mock_repo)
        result = await use_case.execute("test@example.com", "password")
        
        assert result["access_token"] == "token123"
        assert result["refresh_token"] == "refresh123"

@pytest.mark.asyncio
async def test_login_invalid_password():
    mock_repo = AsyncMock()
    
    test_user = MockUser(
        email="test@example.com",
        password_hash="hashed",
        status="ACTIVE"
    )
    
    with patch("src.application.auth.use_cases.UserRepository", return_value=mock_repo), \
         patch("src.application.auth.use_cases.verify_password", return_value=False):
        
        mock_repo.find_by_email = AsyncMock(return_value=test_user)
        
        use_case = LoginUseCase(mock_repo)
        with pytest.raises(UnauthorizedException):
            await use_case.execute("test@example.com", "wrong_password")
