import pytest
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from app.models.upload import UploadProgress, UploadHistory
from app.services.import_engine import ImportEngine, validate_state_transition


def test_validate_state_transition():
    # Valid transitions
    assert validate_state_transition("awaiting_confirm", "confirmed") is True
    assert validate_state_transition("confirmed", "importing") is True
    assert validate_state_transition("importing", "completed") is True
    assert validate_state_transition("importing", "failed") is True

    # Invalid transitions
    assert validate_state_transition("completed", "importing") is False
    assert validate_state_transition("failed", "confirmed") is False


@pytest.mark.asyncio
@patch("app.services.import_engine.FileParser")
@patch("app.services.import_engine.UploadService")
async def test_execute_import_transaction_success(mock_upload_service_class, mock_file_parser_class):
    # Setup mock parser
    mock_parser = MagicMock()
    mock_chunk = MagicMock()
    mock_chunk.data = [
        {"Product SKU": "SKU1", "Store Code": "LOC1", "Units": "10", "Price": "5.0"},
        {"Product SKU": "SKU2", "Store Code": "LOC2", "Units": "20", "Price": "3.5"}
    ]
    mock_chunk.chunk_index = 1
    mock_chunk.total_chunks = 1
    mock_parser.stream_file.return_value = [mock_chunk]
    mock_file_parser_class.return_value = mock_parser

    # Setup mock database session
    db_session = AsyncMock()
    mock_service = mock_upload_service_class.return_value
    mock_service._create_upload_history = AsyncMock()
    
    # Staging temp file
    fd, temp_path = tempfile.mkstemp()
    os.close(fd)
    
    with open(temp_path, "w") as f:
        f.write("test content")

    try:
        mock_upload = UploadProgress(
            id="test-upload-1",
            company_id="company-1",
            user_id="user-1",
            status="confirmed",
            source_config_id="source-1",
            file_type="csv",
            meta_info={
                "source_type": "transaction",
                "staged_file_path": temp_path,
                "mapping_data": {
                    "confirmed_mapping": {
                        "Product SKU": "product_id",
                        "Store Code": "location_id",
                        "Units": "quantity",
                        "Price": "price"
                    }
                }
            }
        )
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_upload
        db_session.execute.return_value = mock_result

        # Run import execution
        engine = ImportEngine(db_session, "company-1")
        await engine.execute_import("test-upload-1", "user-1")

        # Assertions
        assert mock_upload.status == "completed"
        assert mock_upload.progress_percentage == 100
        assert mock_upload.processed_rows == 2
        assert not os.path.exists(temp_path) # Staging file should be cleaned up!
        
        # Verify db.add is called for DataUpload batch record
        db_session.add.assert_called()
        db_session.commit.assert_called()
        
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@pytest.mark.asyncio
async def test_history_endpoints():
    from app.db.session import get_db
    from app.core.deps import get_current_user
    from fastapi.testclient import TestClient
    from app.main import app
    from app.models.core import User
    from app.models.data import SourceConfig, DataUpload
    
    mock_db = AsyncMock()
    mock_user = MagicMock()
    mock_user.company_id = "company-1"
    mock_user.id = "user-1"
    mock_user.role = "planner"
    
    # Overrides
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: mock_user
    
    client = TestClient(app)
    
    # Setup mock query results
    mock_history = UploadHistory(
        id="history-1",
        company_id="company-1",
        user_id="user-1",
        source_config_id="source-1",
        file_name="test.csv",
        file_type="csv",
        file_size=100,
        upload_date=datetime.now(timezone.utc),
        status="completed",
        duration_seconds=10,
        row_count=100,
        error_count=0,
        warning_count=0,
        result_summary={"stages": {"importing": {"duration": "00:00:10", "status": "completed"}}}
    )
    
    mock_data_upload = DataUpload(
        id="upload-1",
        company_id="company-1",
        source_config_id="source-1",
        upload_date=datetime.now(timezone.utc).isoformat(),
        row_count=100,
        data=[]
    )
    mock_data_upload.created_at = datetime.now(timezone.utc)
    
    mock_user_model = User(id="user-1", email="user@company.com", full_name="John Doe")
    mock_config_model = SourceConfig(id="source-1", file_name="sales.csv")
    
    # Mock list query count
    mock_count_res = MagicMock()
    mock_count_res.scalar.return_value = 1
    
    # Mock list query records
    mock_list_res = MagicMock()
    mock_list_res.all.return_value = [(mock_data_upload, mock_config_model)]
    
    # Side effects for list vs detail
    # list count -> list records -> detail join row
    mock_db.execute.side_effect = [mock_count_res, mock_list_res]
    
    # Test GET history list
    resp = client.get("/api/v1/import/history")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_count"] == 1
    assert data["uploads"][0]["file_name"] == "sales.csv"
    
    # Reset side effect for detail query
    mock_detail_row = MagicMock()
    mock_detail_row.first.return_value = (mock_history, mock_user_model, mock_config_model)
    mock_db.execute.side_effect = [mock_detail_row]
    
    # Test GET history detail
    resp = client.get("/api/v1/import/history/history-1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["upload_id"] == "history-1"
    assert data["user"]["name"] == "John Doe"
    assert data["source_config"]["name"] == "sales.csv"
    assert data["stages"]["importing"]["duration"] == "00:00:10"
    
    # Clean overrides
    app.dependency_overrides.clear()
