"""API endpoints for upload history, compliance logging, and audit trails."""

import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.deps import min_role, CurrentUser
from app.schemas.history import UploadHistoryListResponse, UploadHistoryDetailResponse
from app.services.history_service import HistoryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/import", tags=["upload-history"])


@router.get(
    "/history",
    response_model=UploadHistoryListResponse,
    summary="List upload history records",
    description="Retrieve paginated list of upload history logs with status and date filters."
)
async def list_upload_history(
    limit: int = Query(20, ge=1, le=100, description="Page limit"),
    offset: int = Query(0, ge=0, description="Page offset"),
    status: Optional[str] = Query("all", description="Filter by status: all, completed, failed, cancelled"),
    start_date: Optional[datetime] = Query(None, description="Start date (ISO format)"),
    end_date: Optional[datetime] = Query(None, description="End date (ISO format)"),
    user: CurrentUser = Depends(min_role("planner")),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve paginated upload histories."""
    logger.info(f"User {user.id} querying history list. limit={limit}, offset={offset}, status={status}")
    history_service = HistoryService(db, user.company_id)
    return await history_service.list_history(
        limit=limit,
        offset=offset,
        status_filter=status,
        start_date=start_date,
        end_date=end_date
    )


@router.get(
    "/history/{upload_id}",
    response_model=UploadHistoryDetailResponse,
    summary="Get upload history details",
    description="Retrieve complete audit log of a single upload, including stage-by-stage timings."
)
async def get_history_detail(
    upload_id: str,
    user: CurrentUser = Depends(min_role("planner")),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve detailed stage execution audit log for an upload."""
    logger.info(f"User {user.id} querying history details for upload {upload_id}")
    history_service = HistoryService(db, user.company_id)
    detail = await history_service.get_history_detail(upload_id)
    
    if not detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Upload history details not found for ID {upload_id}"
        )
        
    return detail
