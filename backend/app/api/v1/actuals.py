from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.core.deps import min_role, CurrentUser
from app.services.actuals_service import ActualsService
from app.schemas.actuals import ActualsUploadOut

router = APIRouter(prefix="/actuals", tags=["actuals"])


@router.post("/upload", response_model=ActualsUploadOut)
async def upload_actuals(
    session_id: str = Form(..., description="Existing forecast session to attach actuals to"),
    file: UploadFile = File(..., description="CSV with columns: item_id, date, actual_value"),
    user: CurrentUser = Depends(min_role("planner")),
    db: AsyncSession = Depends(get_db),
):
    """Bulk-insert actuals from a CSV, linked to an existing forecast session.

    Validates the session belongs to the caller's company, parses the CSV,
    inserts valid rows, and invalidates the dashboard cache so accuracy metrics
    reflect the new actuals immediately.
    """
    content = await file.read()
    try:
        return await ActualsService(db, user.company_id).upload_csv(session_id, content)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
