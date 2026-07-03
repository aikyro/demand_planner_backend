"""Progress tracking API endpoints for upload system."""

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.deps import min_role, CurrentUser
from app.schemas.progress import (
    UploadProgressResponse, MultipleUploadStatusesResponse, UploadSummaryResponse
)
from app.services.progress_service import ProgressService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/import", tags=["upload-progress"])


@router.get(
    "/uploads/status",
    response_model=MultipleUploadStatusesResponse,
    summary="Get status summary for multiple uploads",
    description="Retrieve status summaries and progress percentages for a list of upload IDs."
)
async def get_multiple_upload_statuses(
    upload_ids: str = Query(..., description="Comma-separated list of upload IDs"),
    user: CurrentUser = Depends(min_role("planner")),
    db: AsyncSession = Depends(get_db)
):
    """
    Query current status and aggregate progress of multiple uploads.
    """
    id_list = [uid.strip() for uid in upload_ids.split(",") if uid.strip()]
    if not id_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide at least one valid upload ID"
        )
        
    logger.info(f"Querying bulk status for user {user.id}, uploads: {id_list}")
    progress_service = ProgressService(db, user.company_id)
    return await progress_service.get_multiple_statuses(id_list)


@router.get(
    "/uploads/{upload_id}/progress",
    response_model=UploadProgressResponse,
    summary="Get detailed stage-by-stage upload progress",
    description="Retrieve detailed progress details for each processing stage and estimated time to completion."
)
async def get_upload_progress(
    upload_id: str,
    user: CurrentUser = Depends(min_role("planner")),
    db: AsyncSession = Depends(get_db)
):
    """
    Get detailed stage-by-stage progress for a specific upload.
    """
    logger.info(f"Querying progress for user {user.id}, upload: {upload_id}")
    progress_service = ProgressService(db, user.company_id)
    progress_response = await progress_service.get_upload_progress(upload_id)
    
    if not progress_response:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Upload {upload_id} not found"
        )
        
    return progress_response


@router.get(
    "/uploads/{upload_id}/summary",
    response_model=UploadSummaryResponse,
    summary="Get upload final processing summary",
    description="Retrieve metrics, row counts, and durations for each processing stage upon completion."
)
async def get_upload_summary(
    upload_id: str,
    user: CurrentUser = Depends(min_role("planner")),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a complete processing summary of an upload, including stage durations.
    """
    logger.info(f"Querying summary for user {user.id}, upload: {upload_id}")
    progress_service = ProgressService(db, user.company_id)
    summary_response = await progress_service.get_upload_summary(upload_id)
    
    if not summary_response:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Upload {upload_id} not found"
        )
        
    return summary_response
