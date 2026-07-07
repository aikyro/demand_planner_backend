import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

@pytest.mark.asyncio
@patch("app.api.v1.dashboard.DashboardService")
async def test_dashboard_executive_filters(mock_service_class):
    # Setup mock
    mock_service_instance = AsyncMock()
    mock_service_instance.get_executive_kpis.return_value = {
        "kpis": [],
        "revenue_forecast": 0,
        "revenue_actual": 0,
        "revenue_trend": 0,
        "volume_forecast": 0,
        "volume_actual": 0,
        "volume_trend": 0,
        "wmape": 0
    }
    mock_service_class.return_value = mock_service_instance

    # Make request with query params
    response = client.get(
        "/api/v1/dashboard/executive",
        params={
            "category": ["FOODS", "HOBBIES"],
            "brand": ["Brand A"],
            "state": ["CA"],
            "store": ["CA_1"],
            "channel": ["RETAIL"]
        },
        headers={"Authorization": "Bearer mock-token"}  # Depends on how auth is mocked
    )

    # Note: If security middleware blocks it without a real token, we might get 401. 
    # This is a quick test to see if we can reach the endpoint or if we need to mock security.
