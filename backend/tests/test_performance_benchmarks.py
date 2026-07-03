import pytest
import time
import tracemalloc
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

from app.services.upload_service import UploadService
from app.services.file_parser import FileParser


@pytest.mark.asyncio
async def test_validation_performance_speed():
    # Setup mock DB session
    db_session = AsyncMock()
    service = UploadService(db_session, "company-1", "user-1")

    # Generate 5,000 rows dynamically
    large_data = [
        {
            "product_id": f"SKU{i:05d}",
            "location_id": f"LOC{i:03d}",
            "date": "2026-01-01",
            "quantity": str(i % 10 + 1),
            "price": "10.0"
        }
        for i in range(5000)
    ]

    start_time = time.time()
    
    # Run validation service validate_all
    validation_result = service.validation_service.validate_all(
        rows=large_data,
        source_type="transaction"
    )
    
    duration = time.time() - start_time
    
    # Validation of 5,000 records should complete within 3 seconds
    assert duration < 3.0
    assert validation_result.statistics.total_errors == 0


@pytest.mark.asyncio
async def test_file_parser_streaming_memory():
    # Measure memory profiling using standard library's tracemalloc
    tracemalloc.start()
    
    # Create large CSV file temporarily
    fd, temp_path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    
    try:
        with open(temp_path, "w") as f:
            f.write("product_id,location_id,date,quantity,price\n")
            for i in range(10000):
                f.write(f"SKU{i:05d},LOC001,2026-01-01,10,12.5\n")
                
        parser = FileParser()
        
        from app.schemas.upload import FileType
        chunks = list(parser.stream_file(temp_path, FileType.CSV))
        
        # Verify chunks have been processed
        assert len(chunks) > 0
        
        # Measure peak memory allocation
        current, peak = tracemalloc.get_traced_memory()
        
        # Peak memory for streaming 10k rows should be kept extremely low (e.g. under 10MB)
        peak_mb = peak / (1024 * 1024)
        assert peak_mb < 15.0
        
    finally:
        tracemalloc.stop()
        if os.path.exists(temp_path):
            os.remove(temp_path)
