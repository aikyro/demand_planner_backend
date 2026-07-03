import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.services.mapping_service import MappingService
from app.services.preview_service import StreamingSummaryCalculator
from app.schemas.preview import MappingValidationResult


def test_suggest_mappings_synonyms():
    # Test abbreviation matching
    cols = ["SKU Code", "Store Code", "Trans Date", "Units Sold"]
    suggested, confidence = MappingService.suggest_mappings(cols, "transaction")
    
    assert suggested["SKU Code"] == "product_id"
    assert suggested["Store Code"] == "location_id"
    assert suggested["Trans Date"] == "date"
    assert suggested["Units Sold"] == "quantity"
    
    assert confidence["SKU Code"] >= 0.75
    assert confidence["Units Sold"] >= 0.75


def test_validate_mappings_transaction():
    # Valid transaction mapping
    mapping = {
        "SKU": "product_id",
        "Store": "location_id",
        "Date": "date",
        "Qty": "quantity"
    }
    res = MappingService.validate_mappings(mapping, "transaction")
    assert res.is_valid is True
    assert len(res.missing_required) == 0

    # Missing required mapping
    invalid_mapping = {
        "SKU": "product_id",
        "Store": "location_id"
    }
    res_invalid = MappingService.validate_mappings(invalid_mapping, "transaction")
    assert res_invalid.is_valid is False
    assert "date" in res_invalid.missing_required
    assert "quantity" in res_invalid.missing_required


def test_validate_mappings_lookup():
    # Valid lookup mapping
    mapping = {
        "SKU": "product_id",
        "Store": "location_id"
    }
    res = MappingService.validate_mappings(mapping, "lookup")
    assert res.is_valid is True

    # Missing required mapping
    invalid_mapping = {
        "SKU": "product_id"
    }
    res_invalid = MappingService.validate_mappings(invalid_mapping, "lookup")
    assert res_invalid.is_valid is False
    assert "location_id" in res_invalid.missing_required


def test_streaming_summary_calculator():
    cols = ["product", "location", "date", "quantity"]
    calc = StreamingSummaryCalculator(cols)
    
    # 2 rows, 1 duplicate
    rows = [
        {"product": "SKU1", "location": "LOC1", "date": "2026-01-01", "quantity": "10"},
        {"product": "SKU1", "location": "LOC1", "date": "2026-01-01", "quantity": "10"}
    ]
    calc.process_chunk(rows)
    
    summary = calc.get_summary(file_size=100, file_type="csv")
    
    assert summary["row_count"] == 2
    assert summary["duplicate_rows"] == 1
    assert summary["column_types"]["date"] == "date"
    assert summary["column_types"]["quantity"] == "numeric"
    assert summary["date_ranges"]["date"]["start"] == "2026-01-01"
    assert summary["date_ranges"]["date"]["end"] == "2026-01-01"


@pytest.mark.asyncio
async def test_preview_endpoints():
    from app.db.session import get_db
    from app.core.deps import get_current_user
    from fastapi.testclient import TestClient
    from app.main import app
    from app.models.upload import UploadProgress
    
    mock_db = AsyncMock()
    mock_user = MagicMock()
    mock_user.company_id = "company-1"
    mock_user.id = "user-1"
    mock_user.role = "planner"
    
    # Overrides
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: mock_user
    
    client = TestClient(app)
    
    # Mock database queries
    mock_upload = UploadProgress(
        id="test-upload-id",
        company_id="company-1",
        user_id="user-1",
        status="completed",
        total_rows=10,
        source_config_id="source-1",
        meta_info={
            "preview_data": {
                "first_rows": [{"col1": "val1"}],
                "last_rows": [{"col1": "val2"}]
            },
            "summary": {
                "row_count": 10,
                "column_count": 1,
                "file_size": 100,
                "file_type": "csv",
                "encoding": "UTF-8",
                "estimated_memory_usage": "0.1 MB",
                "missing_values": {},
                "duplicate_rows": 0,
                "date_ranges": {},
                "column_types": {"col1": "string"}
            },
            "mapping_data": {
                "suggested_mapping": {"col1": "product_id"},
                "confidence_scores": {"col1": 1.0}
            }
        }
    )
    
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_upload
    mock_db.execute.return_value = mock_result
    
    # Test GET preview
    resp = client.get("/api/v1/import/uploads/test-upload-id/preview")
    assert resp.status_code == 200
    data = resp.json()
    assert data["upload_id"] == "test-upload-id"
    assert data["preview_data"]["first_rows"] == [{"col1": "val1"}]
    
    # Test GET data-summary
    resp = client.get("/api/v1/import/uploads/test-upload-id/data-summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["row_count"] == 10
    
    # Test GET suggest mappings
    resp = client.get("/api/v1/import/uploads/test-upload-id/mapping/suggest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["suggested_mapping"] == {"col1": "product_id"}
    
    # Test PUT mappings
    resp = client.put("/api/v1/import/uploads/test-upload-id/mapping", json={
        "column_mappings": {"col1": "product_id"}
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "mapping_saved"
    
    # Test POST confirm
    mock_cfg = MagicMock()
    mock_cfg.id = "source-1"
    mock_cfg.company_id = "company-1"
    mock_cfg.column_mappings = {}
    
    mock_result_cfg = MagicMock()
    mock_result_cfg.scalar_one_or_none.side_effect = [mock_upload, mock_cfg]
    mock_db.execute.return_value = mock_result_cfg
    
    resp = client.post("/api/v1/import/uploads/test-upload-id/confirm", json={
        "column_mappings": {"col1": "product_id"},
        "proceed_with_warnings": True
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "confirmed"
    
    # Clean overrides
    app.dependency_overrides.clear()
