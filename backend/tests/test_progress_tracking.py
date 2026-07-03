import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta, timezone

from app.models.upload import UploadProgress
from app.schemas.upload import UploadStatus
from app.services.progress_service import ProgressService, STAGE_ORDER


@pytest.mark.asyncio
async def test_progress_service_status_mapping():
    db_session = AsyncMock()
    service = ProgressService(db_session, "company-1")

    # Completed status
    assert service.get_active_stage("completed", None) == "completed"

    # Active status mapping
    assert service.get_active_stage("parsing", "parse") == "parsing"
    assert service.get_active_stage("validating", "validate") == "validating"
    assert service.get_active_stage("uploading", "upload") == "uploading"
    assert service.get_active_stage("pending", "upload") == "uploading"
    assert service.get_active_stage("importing", "import") == "importing"


@pytest.mark.asyncio
async def test_progress_service_calculate_stage_progress():
    db_session = AsyncMock()
    service = ProgressService(db_session, "company-1")

    # In validating stage (40% overall)
    # offset: 40, weight: 40 -> validating progress is 50%
    upload = UploadProgress(
        id="test-upload-1",
        status="validating",
        current_stage="validate",
        progress_percentage=60, # 40 + (0.5 * 40) = 60
        processed_rows=0,
        total_rows=0,
        created_at=datetime.now(timezone.utc)
    )

    stage_progress = service.calculate_stage_progress(upload)

    # Prior stages must be completed
    assert stage_progress["uploading"].percentage == 100
    assert stage_progress["uploading"].status == "completed"
    assert stage_progress["parsing"].percentage == 100
    assert stage_progress["parsing"].status == "completed"

    # Current stage
    assert stage_progress["validating"].percentage == 50
    assert stage_progress["validating"].status == "in_progress"

    # Subsequent stages must be pending
    assert stage_progress["previewing"].percentage == 0
    assert stage_progress["previewing"].status == "pending"


@pytest.mark.asyncio
async def test_progress_service_precise_row_based_validation_progress():
    db_session = AsyncMock()
    service = ProgressService(db_session, "company-1")

    # If processed rows and total rows are known during validating, use them
    upload = UploadProgress(
        id="test-upload-1",
        status="validating",
        current_stage="validate",
        progress_percentage=60,
        processed_rows=75,
        total_rows=100,
        created_at=datetime.now(timezone.utc)
    )

    stage_progress = service.calculate_stage_progress(upload)
    
    # 75/100 = 75% validating progress
    assert stage_progress["validating"].percentage == 75


@pytest.mark.asyncio
async def test_progress_service_overall_progress_calculation():
    db_session = AsyncMock()
    service = ProgressService(db_session, "company-1")

    upload = UploadProgress(
        id="test-upload-1",
        status="validating",
        current_stage="validate",
        progress_percentage=60,
        processed_rows=0,
        total_rows=0,
        created_at=datetime.now(timezone.utc)
    )

    stage_progress = service.calculate_stage_progress(upload)
    overall_p = service.calculate_overall_progress(upload, stage_progress)

    # uploading (20% * 100) + parsing (20% * 100) + validating (40% * 50) = 20 + 20 + 20 = 60
    assert overall_p == 60


@pytest.mark.asyncio
async def test_progress_service_eta_calculation():
    db_session = AsyncMock()
    service = ProgressService(db_session, "company-1")

    # Upload started 10 seconds ago, progress is 50%
    start_time = datetime.now(timezone.utc) - timedelta(seconds=10)
    upload = UploadProgress(
        id="test-upload-1",
        status="validating",
        current_stage="validate",
        progress_percentage=50,
        created_at=start_time
    )

    eta = service.calculate_eta(upload)
    
    # Remaining progress = 50%. Elapsed = 10s. Rate = 5% per second.
    # Remaining time should be 10s.
    assert eta is not None
    diff = eta - datetime.now(timezone.utc)
    assert abs(diff.total_seconds() - 10) < 2.0


@pytest.mark.asyncio
async def test_progress_service_get_stage_durations():
    db_session = AsyncMock()
    service = ProgressService(db_session, "company-1")

    # Storing timestamps inside meta_info
    start_time = datetime(2026, 7, 1, 12, 0, 0)
    end_time = datetime(2026, 7, 1, 12, 0, 15) # 15 seconds
    
    upload = UploadProgress(
        id="test-upload-1",
        status="completed",
        meta_info={
            "stage_timestamps": {
                "uploading": {
                    "start": start_time.isoformat(),
                    "end": end_time.isoformat()
                }
            }
        }
    )

    durations = service.get_stage_durations(upload)
    assert durations["uploading"].duration == "00:00:15"
    assert durations["parsing"].duration is None
