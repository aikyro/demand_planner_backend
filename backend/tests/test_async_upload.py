import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from app.services.task_manager import TaskManager
from app.services.upload_service import UploadService
from app.models.upload import UploadProgress, ValidationError, UploadHistory
from app.schemas.upload import UploadStatus, FileType
from app.tasks.upload_tasks import process_upload_task, _run_upload_processing

@pytest.mark.asyncio
async def test_task_manager_register_task():
    # Setup mock database session
    db_session = AsyncMock()
    
    # Mock return value for query
    mock_upload = UploadProgress(
        id="test-upload-id",
        company_id="company-1",
        user_id="user-1",
        status="pending",
        meta_info={}
    )
    
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_upload
    db_session.execute.return_value = mock_result
    
    # Instantiate TaskManager
    task_manager = TaskManager(db_session)
    
    # Register task
    await task_manager.register_task("test-upload-id", "celery-task-123")
    
    # Assertions
    db_session.execute.assert_called_once()
    assert mock_upload.meta_info["task_id"] == "celery-task-123"
    db_session.flush.assert_called_once()


@pytest.mark.asyncio
@patch("app.services.task_manager.celery_app")
async def test_task_manager_cancel_task(mock_celery_app):
    # Setup mock database session
    db_session = AsyncMock()
    
    # Mock return value for query
    mock_upload = UploadProgress(
        id="test-upload-id",
        company_id="company-1",
        user_id="user-1",
        status="parsing",
        meta_info={"task_id": "celery-task-123"}
    )
    
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_upload
    db_session.execute.return_value = mock_result
    
    # Instantiate TaskManager
    task_manager = TaskManager(db_session)
    
    # Cancel task
    success = await task_manager.cancel_upload_task("test-upload-id")
    
    # Assertions
    assert success is True
    assert mock_upload.status == UploadStatus.CANCELLED.value
    assert mock_upload.completed_at is not None
    mock_celery_app.control.revoke.assert_called_once_with("celery-task-123", terminate=True)
    db_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_upload_service_is_cancelled():
    # Setup mock database session
    db_session = AsyncMock()
    
    # Mock result for cancelled upload
    mock_result_cancelled = MagicMock()
    mock_result_cancelled.scalar_one_or_none.return_value = UploadStatus.CANCELLED.value
    
    # Mock result for active upload
    mock_result_active = MagicMock()
    mock_result_active.scalar_one_or_none.return_value = UploadStatus.PARSING.value
    
    # Instantiate UploadService
    service = UploadService(db_session, "company-1", "user-1")
    
    # Test cancelled case
    db_session.execute.return_value = mock_result_cancelled
    assert await service._is_cancelled("test-id") is True
    
    # Test active case
    db_session.execute.return_value = mock_result_active
    assert await service._is_cancelled("test-id") is False


@pytest.mark.asyncio
@patch("app.services.upload_service.logger")
async def test_upload_service_process_upload_file_async(mock_logger):
    # Setup mock database session
    db_session = AsyncMock()
    
    # Mock UploadProgress
    mock_upload = UploadProgress(
        id="test-upload-id",
        company_id="company-1",
        user_id="user-1",
        status="pending",
        file_name="test.csv",
        file_type="csv",
        meta_info={"source_type": "transaction"}
    )
    
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_upload
    db_session.execute.return_value = mock_result
    
    # Instantiate UploadService
    service = UploadService(db_session, "company-1", "user-1")
    
    # Mock FileParser validation and streaming
    service.file_parser = MagicMock()
    
    mock_validation = MagicMock()
    mock_validation.is_valid = True
    mock_validation.file_format = FileType.CSV
    service.file_parser.validate_file.return_value = mock_validation
    service.file_parser._detect_csv_delimiter.return_value = ","
    service.file_parser._count_csv_rows.return_value = 100
    
    # Mock stream_file chunks
    mock_chunk = MagicMock()
    mock_chunk.chunk_index = 1
    mock_chunk.total_chunks = 1
    mock_chunk.row_count = 100
    mock_chunk.start_row = 0
    mock_chunk.data = [{"col1": "val1"}]
    service.file_parser.stream_file.return_value = [mock_chunk]
    
    # Mock _validate_data results
    mock_validation_result = MagicMock()
    mock_validation_result.errors = []
    service._validate_data = AsyncMock(return_value=mock_validation_result)
    
    # Mock _create_upload_history and cleanup_temp_files
    service._create_upload_history = AsyncMock()
    service.cleanup_temp_files = AsyncMock()
    
    # Execute processing
    await service.process_upload_file_async("test-upload-id", "mock/path/test.csv")
    
    # Assertions
    assert mock_upload.status == "awaiting_confirm"
    assert mock_upload.progress_percentage == 90
    assert mock_upload.total_rows == 100
    assert mock_upload.processed_rows == 100
    
    service._create_upload_history.assert_called_once_with(mock_upload)
    service.cleanup_temp_files.assert_not_called()
    
    # 2 commits: one for start processing, one for completion
    assert db_session.commit.call_count >= 2
