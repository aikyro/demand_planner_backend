import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.core.deps import get_current_user
from app.db.session import get_db

client = TestClient(app)


@pytest.fixture
def mock_auth_and_db():
    mock_db = AsyncMock()
    mock_user = MagicMock()
    mock_user.company_id = "company-1"
    mock_user.id = "viewer-user"
    mock_user.role = "viewer"

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: mock_user
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
@patch("app.api.v1.dashboard.DashboardService")
async def test_dashboard_executive_filters(mock_service_class, mock_auth_and_db):
    # Setup mock
    mock_service_instance = AsyncMock()
    mock_service_instance.executive_kpis.return_value = ({
        "total_forecasts": 0,
        "active_items": 0,
        "total_predicted": 0.0,
        "total_actual": 0.0,
        "overall_accuracy": 0.0,
        "bias_pct": 0.0,
        "matched_points": 0,
        "session_count": 0,
        "trend": [],
        "recent_sessions": [],
    }, True)
    mock_service_class.return_value = mock_service_instance

    # Make request with query params
    response = client.get(
        "/api/v1/dashboard/executive",
        params={
            "category": "FOODS",
            "brand": "Brand A",
            "state": "CA",
            "store": "CA_1",
            "channel": "RETAIL"
        }
    )

    assert response.status_code == 200
    assert response.headers.get("X-Cache") == "HIT"


@pytest.mark.asyncio
@patch("app.api.v1.dashboard.DashboardService")
async def test_dashboard_executive_cache_miss(mock_service_class, mock_auth_and_db):
    # Setup mock
    mock_service_instance = AsyncMock()
    mock_service_instance.executive_kpis.return_value = ({
        "total_forecasts": 0,
        "active_items": 0,
        "total_predicted": 0.0,
        "total_actual": 0.0,
        "overall_accuracy": 0.0,
        "bias_pct": 0.0,
        "matched_points": 0,
        "session_count": 0,
        "trend": [],
        "recent_sessions": [],
    }, False)
    mock_service_class.return_value = mock_service_instance

    response = client.get("/api/v1/dashboard/executive")

    assert response.status_code == 200
    assert response.headers.get("X-Cache") == "MISS"


@pytest.mark.asyncio
@patch("app.api.v1.dashboard.DashboardService")
async def test_kpis_cache_hit(mock_service_class, mock_auth_and_db):
    mock_service_instance = AsyncMock()
    mock_service_instance.kpis.return_value = ({
        "total_quantity": 100.0,
        "total_revenue": 500.0,
        "sku_count": 5,
        "location_count": 2,
        "monthly_volume": [],
    }, True)
    mock_service_class.return_value = mock_service_instance

    response = client.get("/api/v1/kpis")

    assert response.status_code == 200
    assert response.headers.get("X-Cache") == "HIT"
