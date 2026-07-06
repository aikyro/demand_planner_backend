import json

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.deps import get_current_user, CurrentUser
from app.services.generated_service import GeneratedService

router = APIRouter(prefix="/generated", tags=["generated"])


@router.get("/sessions")
async def list_generated_sessions(
    status_filter: str | None = Query(None, alias="status", description="e.g. published or draft"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Forecast sessions with generated-data stats (item/row counts, model used)."""
    return await GeneratedService(db, user.company_id).list_sessions(status_filter, page, page_size)


@router.get("/{session_id}/preview/{table_type}")
async def preview_generated(
    session_id: str,
    table_type: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Column names + first 10 rows of modeling_data or forecasts for a session."""
    try:
        return await GeneratedService(db, user.company_id).preview(session_id, table_type)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.get("/{session_id}/download/{table_type}")
async def download_generated(
    session_id: str,
    table_type: str,
    rename: str | None = Query(
        None, description='JSON object mapping original column names to export aliases',
    ),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream a full generated table as CSV, optionally with renamed headers."""
    rename_map: dict[str, str] = {}
    if rename:
        try:
            parsed = json.loads(rename)
            if not isinstance(parsed, dict):
                raise ValueError
            rename_map = {str(k): str(v) for k, v in parsed.items()}
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "rename must be a JSON object")

    svc = GeneratedService(db, user.company_id)
    try:
        # Validate session/type up-front so errors are 4xx, not mid-stream failures.
        await svc.preview(session_id, table_type)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    filename = f"{table_type}-{session_id}.csv"
    return StreamingResponse(
        svc.export_csv(session_id, table_type, rename_map),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{session_id}/forecast-rows")
async def forecast_rows(
    session_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Paginated forecast rows (id, item_id, date, predictions) for the override editor."""
    try:
        return await GeneratedService(db, user.company_id).forecast_rows(session_id, page, page_size)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
