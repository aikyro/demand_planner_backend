import pytest
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from app.services.upload_service import UploadService
from app.models.upload import UploadProgress
from app.schemas.upload import FileType, UploadStatus

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.mark.asyncio
async def test_upload_service_zero_byte_file():
    db_session = AsyncMock()
    service = UploadService(db_session, "company-1", "user-1")

    # Create a 0-byte temporary file
    with tempfile.NamedTemporaryFile(delete=False) as temp_f:
        temp_path = temp_f.name

    try:
        validation_res = service.file_parser.validate_file(temp_path)
        # 0-byte files should be detected as empty
        assert validation_res.is_valid is False or validation_res.is_empty is True
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@pytest.mark.asyncio
@patch("app.services.upload_service.logger")
async def test_upload_service_malformed_csv_validation(mock_logger):
    # Setup mock DB session
    db_session = AsyncMock()
    
    mock_upload = UploadProgress(
        id="test-upload-malformed",
        company_id="company-1",
        user_id="user-1",
        status="pending",
        file_name="malformed.csv",
        file_type="csv",
        file_size=100,
        created_at=datetime.now(timezone.utc),
        meta_info={"source_type": "transaction"}
    )
    
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_upload
    db_session.execute.return_value = mock_result

    service = UploadService(db_session, "company-1", "user-1")
    
    # Create a temp file with a row missing a required value to trigger schema warning (non-blocking)
    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as f:
        f.write("product_id,location_id,quantity,date\n,STORE001,10,2026-07-02\n")
        temp_path = f.name

    try:
        response = await service.process_upload_file(
            upload_id="test-upload-malformed",
            file_path=temp_path,
            validate_immediately=True
        )
        
        assert response.status == UploadStatus.AWAITING_CONFIRM
        assert response.warning_count > 0
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@pytest.mark.asyncio
async def test_upload_service_invalid_upload_id():
    db_session = AsyncMock()
    
    # Mock database to return None for get_upload
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db_session.execute.return_value = mock_result
    
    service = UploadService(db_session, "company-1", "user-1")
    
    with pytest.raises(ValueError, match="Upload nonexistent-id not found"):
        await service.process_upload_file_async("nonexistent-id", "mock/path.csv")
