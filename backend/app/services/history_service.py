"""Service for querying upload histories and detailed stage statistics."""

import logging
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UploadHistory, DataUpload, User, SourceConfig
from app.schemas.history import (
    UploadHistoryItem, UploadHistoryListResponse, UploadHistoryDetailResponse,
    HistoryUserSummary, HistorySourceConfigSummary, HistoryStageInfo
)

logger = logging.getLogger(__name__)


class HistoryService:
    """Service to query upload history audit trails and stage executions."""

    def __init__(self, db: AsyncSession, company_id: str):
        """
        Initialize HistoryService.

        Args:
            db: Database session
            company_id: Company context identifier
        """
        self.db = db
        self.company_id = company_id

    async def list_history(
        self,
        limit: int = 20,
        offset: int = 0,
        status_filter: Optional[str] = "all",
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> UploadHistoryListResponse:
        """
        Retrieve paginated upload history records directly from data_uploads table.

        Args:
            limit: Pagination limit
            offset: Pagination offset
            status_filter: Filter by upload status
            start_date: Filter uploads from this date
            end_date: Filter uploads to this date

        Returns:
            UploadHistoryListResponse
        """
        # Support querying histories by status
        stmt = (
            select(UploadHistory, SourceConfig)
            .join(SourceConfig, UploadHistory.source_config_id == SourceConfig.id)
            .where(UploadHistory.company_id == self.company_id)
        )
        
        # Apply filters
        if status_filter and status_filter.lower() != "all":
            stmt = stmt.where(UploadHistory.status == status_filter.lower())
        else:
            stmt = stmt.where(UploadHistory.status == "completed")
            
        if start_date:
            stmt = stmt.where(UploadHistory.upload_date >= start_date)
            
        if end_date:
            stmt = stmt.where(UploadHistory.upload_date <= end_date)
            
        # Get count query
        count_stmt = select(func.count()).select_from(stmt.subquery())
        count_result = await self.db.execute(count_stmt)
        total_count = count_result.scalar() or 0
        
        # Get elements sorted by UploadHistory.upload_date desc
        stmt = stmt.order_by(UploadHistory.upload_date.desc()).limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        records = result.all()
        
        items = []
        for uh, sc in records:
            duration_str = None
            if uh.duration_seconds is not None:
                secs = uh.duration_seconds
                hours = secs // 3600
                mins = (secs % 3600) // 60
                s = secs % 60
                duration_str = f"{hours:02d}:{mins:02d}:{s:02d}"
                
            summary = uh.result_summary or {}
            columns = summary.get("columns")
            if not columns and sc.column_mappings:
                columns = list(sc.column_mappings.values())
                
            items.append(
                UploadHistoryItem(
                    upload_id=uh.id,
                    file_name=uh.file_name,
                    upload_date=uh.upload_date,
                    status=uh.status,
                    duration=duration_str,
                    row_count=uh.row_count,
                    error_count=uh.error_count,
                    warning_count=uh.warning_count,
                    file_size=uh.file_size,
                    file_type=uh.file_type,
                    columns=columns
                )
            )
            
        return UploadHistoryListResponse(total_count=total_count, uploads=items)

    async def get_history_detail(self, upload_id: str) -> Optional[UploadHistoryDetailResponse]:
        """
        Get detailed stages, associated configurations, and user details of a single upload history.

        Args:
            upload_id: Unique upload identifier

        Returns:
            UploadHistoryDetailResponse or None if not found
        """
        # Joint query for history, user, and config
        stmt = select(UploadHistory, User, SourceConfig).\
            outerjoin(User, User.id == UploadHistory.user_id).\
            outerjoin(SourceConfig, SourceConfig.id == UploadHistory.source_config_id).\
            where(UploadHistory.id == upload_id, UploadHistory.company_id == self.company_id)
            
        result = await self.db.execute(stmt)
        row = result.first()
        if not row:
            return None
            
        r, u, c = row
        
        duration_str = None
        if r.duration_seconds is not None:
            secs = r.duration_seconds
            hours = secs // 3600
            mins = (secs % 3600) // 60
            s = secs % 60
            duration_str = f"{hours:02d}:{mins:02d}:{s:02d}"
            
        # Parse stages dictionary from summary
        summary = r.result_summary or {}
        stages_data = summary.get("stages", {})
        
        stages = {}
        for stage, val in stages_data.items():
            stages[stage] = HistoryStageInfo(
                duration=val.get("duration"),
                status=val.get("status", "completed")
            )
            
        user_summary = None
        if u:
            user_summary = HistoryUserSummary(
                id=u.id,
                name=u.full_name or u.email
            )
            
        config_summary = None
        if c:
            config_summary = HistorySourceConfigSummary(
                id=c.id,
                name=c.file_name or f"Config {c.id[:8]}"
            )
            
        # Determine completed date if duration and upload date are present
        completed_date = None
        if r.upload_date and r.duration_seconds is not None:
            from datetime import timedelta
            completed_date = r.upload_date + timedelta(seconds=r.duration_seconds)
            
        return UploadHistoryDetailResponse(
            upload_id=r.id,
            file_name=r.file_name,
            upload_date=r.upload_date,
            completed_date=completed_date,
            duration=duration_str,
            status=r.status,
            row_count=r.row_count,
            error_count=r.error_count,
            warning_count=r.warning_count,
            file_size=r.file_size,
            file_type=r.file_type,
            user=user_summary,
            source_config=config_summary,
            stages=stages
        )
