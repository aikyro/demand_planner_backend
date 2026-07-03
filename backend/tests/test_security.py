import pytest
from unittest.mock import MagicMock, AsyncMock
from fastapi.testclient import TestClient

from app.services.upload_service import sanitize_filename
from app.main import app
from app.db.session import get_db
from app.core.deps import get_current_user


def test_sanitize_filename_path_traversal():
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("..\\..\\windows\\win.ini") == "win.ini"

    # Absolute paths
    assert sanitize_filename("/absolute/path/file.csv") == "file.csv"
    assert sanitize_filename("C:\\absolute\\path\\file.csv") == "file.csv"

    # Dangerous characters removal
    assert sanitize_filename("test;echo 'hello'.csv") == "testecho hello.csv"


def test_endpoint_authorization_role_ranks():
    mock_db = AsyncMock()
    mock_viewer = MagicMock()
    mock_viewer.company_id = "company-1"
    mock_viewer.id = "viewer-user"
    mock_viewer.role = "viewer"  # Non-authorized role

    # Overrides for unauthorized user
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: mock_viewer

    client = TestClient(app)

    # Any import data confirmation trigger should be forbidden for 'viewer' role
    resp = client.post(
        "/api/v1/import/uploads/test-upload-id/import",
        json={"column_mappings": {}, "proceed_with_warnings": True}
    )
    assert resp.status_code == 403
    assert "detail" in resp.json()

    # Clear overrides
    app.dependency_overrides.clear()
