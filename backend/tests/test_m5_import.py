import pytest
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.upload import UploadProgress
from app.models import Calendar, SellPrice, Sales
from app.services.import_engine import ImportEngine


@pytest.mark.asyncio
@patch("app.services.import_engine.FileParser")
@patch("app.services.import_engine.UploadService")
async def test_execute_import_m5_calendar(mock_upload_service_class, mock_file_parser_class):
    mock_parser = MagicMock()
    mock_chunk = MagicMock()
    mock_chunk.data = [
        {
            "date": "2011-01-29",
            "wm_yr_wk": "11101",
            "weekday": "Saturday",
            "wday": "1",
            "month": "1",
            "year": "2011",
            "d": "d_1",
            "event_name_1": "NaN",  # Test NaN handling
            "event_type_1": "",
            "snap_CA": "0",
            "snap_TX": "0",
            "snap_WI": "0"
        }
    ]
    mock_chunk.chunk_index = 1
    mock_chunk.total_chunks = 1
    mock_parser.stream_file.return_value = [mock_chunk]
    mock_file_parser_class.return_value = mock_parser

    db_session = AsyncMock()
    mock_service = mock_upload_service_class.return_value
    mock_service._create_upload_history = AsyncMock()

    fd, temp_path = tempfile.mkstemp()
    os.close(fd)

    try:
        mock_upload = UploadProgress(
            id="test-upload-calendar",
            company_id="company-1",
            user_id="user-1",
            status="confirmed",
            source_config_id="source-calendar",
            file_type="csv",
            meta_info={
                "source_type": "calendar",
                "staged_file_path": temp_path,
                "mapping_data": {
                    "confirmed_mapping": {
                        "date": "date",
                        "wm_yr_wk": "wm_yr_wk",
                        "weekday": "weekday",
                        "wday": "wday",
                        "month": "month",
                        "year": "year",
                        "d": "d",
                        "event_name_1": "event_name_1",
                        "event_type_1": "event_type_1",
                        "snap_CA": "snap_CA",
                        "snap_TX": "snap_TX",
                        "snap_WI": "snap_WI"
                    }
                }
            }
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_upload
        db_session.execute.return_value = mock_result

        engine = ImportEngine(db_session, "company-1")
        await engine.execute_import("test-upload-calendar", "user-1")

        assert mock_upload.status == "completed"
        assert mock_upload.processed_rows == 1

        # Check if database execute was called with list of dicts for Calendar bulk insert
        execute_calls = db_session.execute.call_args_list
        insert_args = [call[0] for call in execute_calls if len(call[0]) > 1 and isinstance(call[0][1], list)]
        assert len(insert_args) == 1
        
        batch_data = insert_args[0][1]
        assert len(batch_data) == 1
        
        cal = batch_data[0]
        assert cal["d"] == "d_1"
        assert cal["wm_yr_wk"] == 11101
        assert cal["event_name_1"] is None  # NaN got converted to None!

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@pytest.mark.asyncio
@patch("app.services.import_engine.FileParser")
@patch("app.services.import_engine.UploadService")
async def test_execute_import_m5_sell_prices(mock_upload_service_class, mock_file_parser_class):
    mock_parser = MagicMock()
    mock_chunk = MagicMock()
    mock_chunk.data = [
        {
            "store_id": "CA_1",
            "item_id": "HOBBIES_1_001",
            "wm_yr_wk": "11101",
            "sell_price": "9.58"
        }
    ]
    mock_chunk.chunk_index = 1
    mock_chunk.total_chunks = 1
    mock_parser.stream_file.return_value = [mock_chunk]
    mock_file_parser_class.return_value = mock_parser

    db_session = AsyncMock()
    mock_service = mock_upload_service_class.return_value
    mock_service._create_upload_history = AsyncMock()

    fd, temp_path = tempfile.mkstemp()
    os.close(fd)

    try:
        mock_upload = UploadProgress(
            id="test-upload-prices",
            company_id="company-1",
            user_id="user-1",
            status="confirmed",
            source_config_id="source-prices",
            file_type="csv",
            meta_info={
                "source_type": "sell_prices",
                "staged_file_path": temp_path,
                "mapping_data": {
                    "confirmed_mapping": {
                        "store_id": "store_id",
                        "item_id": "item_id",
                        "wm_yr_wk": "wm_yr_wk",
                        "sell_price": "sell_price"
                    }
                }
            }
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_upload
        db_session.execute.return_value = mock_result

        engine = ImportEngine(db_session, "company-1")
        await engine.execute_import("test-upload-prices", "user-1")

        assert mock_upload.status == "completed"
        assert mock_upload.processed_rows == 1

        execute_calls = db_session.execute.call_args_list
        insert_args = [call[0] for call in execute_calls if len(call[0]) > 1 and isinstance(call[0][1], list)]
        assert len(insert_args) == 1
        
        batch_data = insert_args[0][1]
        assert len(batch_data) == 1
        
        prc = batch_data[0]
        assert prc["store_id"] == "CA_1"
        assert prc["sell_price"] == 9.58

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@pytest.mark.asyncio
@patch("app.services.import_engine.FileParser")
@patch("app.services.import_engine.UploadService")
async def test_execute_import_m5_sales(mock_upload_service_class, mock_file_parser_class):
    mock_parser = MagicMock()
    mock_chunk = MagicMock()
    mock_chunk.data = [
        {
            "id": "HOBBIES_1_001_CA_1_evaluation",
            "item_id": "HOBBIES_1_001",
            "dept_id": "HOBBIES_1",
            "cat_id": "HOBBIES",
            "store_id": "CA_1",
            "state_id": "CA",
            "d": "d_1"
        }
    ]
    mock_chunk.chunk_index = 1
    mock_chunk.total_chunks = 1
    mock_parser.stream_file.return_value = [mock_chunk]
    mock_file_parser_class.return_value = mock_parser

    db_session = AsyncMock()
    mock_service = mock_upload_service_class.return_value
    mock_service._create_upload_history = AsyncMock()

    fd, temp_path = tempfile.mkstemp()
    os.close(fd)

    try:
        mock_upload = UploadProgress(
            id="test-upload-sales",
            company_id="company-1",
            user_id="user-1",
            status="confirmed",
            source_config_id="source-sales",
            file_type="csv",
            meta_info={
                "source_type": "sales",
                "staged_file_path": temp_path,
                "mapping_data": {
                    "confirmed_mapping": {
                        "id": "id",
                        "item_id": "item_id",
                        "dept_id": "dept_id",
                        "cat_id": "cat_id",
                        "store_id": "store_id",
                        "state_id": "state_id",
                        "d": "d"
                    }
                }
            }
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_upload
        db_session.execute.return_value = mock_result

        engine = ImportEngine(db_session, "company-1")
        await engine.execute_import("test-upload-sales", "user-1")

        assert mock_upload.status == "completed"
        assert mock_upload.processed_rows == 1

        execute_calls = db_session.execute.call_args_list
        insert_args = [call[0] for call in execute_calls if len(call[0]) > 1 and isinstance(call[0][1], list)]
        assert len(insert_args) == 1
        
        batch_data = insert_args[0][1]
        assert len(batch_data) == 1
        
        sal = batch_data[0]
        assert sal["item_id"] == "HOBBIES_1_001"
        assert sal["d"] == "d_1"

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
