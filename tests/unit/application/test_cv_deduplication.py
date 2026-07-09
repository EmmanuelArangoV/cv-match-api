import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
from src.application.cv.use_cases import UploadCVsUseCase
from src.infrastructure.db.models import ProcessStatus, HiringProcess

@pytest.mark.asyncio
async def test_cv_deduplication():
    mock_db = AsyncMock()
    
    mock_process = HiringProcess(id=uuid.uuid4(), status=ProcessStatus.CVS_UPLOADED.value, budget_max_usd=100.0)
    
    with patch("src.application.cv.use_cases.ProcessRepository") as mock_process_repo, \
         patch("src.application.cv.use_cases.CandidateRepository") as mock_cand_repo:
         
        mock_process_repo_instance = mock_process_repo.return_value
        mock_process_repo_instance.find_by_id = AsyncMock(return_value=mock_process)
        
        mock_cand_repo_instance = mock_cand_repo.return_value
        
        mock_existing_candidate = MagicMock()
        mock_existing_candidate.id = uuid.uuid4()
        mock_cand_repo_instance.find_by_cv_file_hash = AsyncMock(return_value=mock_existing_candidate)
        mock_cand_repo_instance.count_by_process = AsyncMock(return_value=0)
        
        # Simulate that this candidate is already linked to this process
        mock_existing_pc = MagicMock()
        mock_existing_pc.id = uuid.uuid4()
        mock_cand_repo_instance.find_process_candidate = AsyncMock(return_value=mock_existing_pc)
        
        use_case = UploadCVsUseCase(mock_db)
        
        # We need a mock UploadFile
        mock_file = AsyncMock()
        mock_file.filename = "test.pdf"
        mock_file.size = 1000
        mock_file.read.return_value = b"test content"
        
        with patch("src.application.cv.use_cases.hashlib.sha256") as mock_hash:
            mock_hash.return_value.hexdigest.return_value = "hash123"
            
            # Need to mock the DB execution for budget
            result_mock = MagicMock()
            result_mock.scalar.return_value = 0.0
            mock_db.execute = AsyncMock(return_value=result_mock)
            
            results = await use_case.execute(
                process_id=mock_process.id,
                files=[mock_file],
                uploader_id=uuid.uuid4()
            )
            
            assert len(results) == 1
            assert results[0].task_id == "already_exists"
