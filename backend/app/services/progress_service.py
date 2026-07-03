"""Service for calculating upload progress, stage durations, and ETAs."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.upload import UploadProgress
from app.schemas.upload import UploadStatus
from app.schemas.progress import (
    StageProgressDetail, UploadProgressResponse, UploadStatusItem,
    MultipleUploadStatusesResponse, StageDuration, UploadSummaryResponse
)

logger = logging.getLogger(__name__)

STAGE_ORDER = [
    "uploading",
    "parsing",
    "validating",
    "previewing",
    "confirmed",
    "importing"
]

STAGE_WEIGHTS = {
    "uploading": 0.20,   # 20%
    "parsing": 0.20,     # 20%
    "validating": 0.40,  # 40%
    "previewing": 0.10,  # 10%
    "confirmed": 0.05,   # 5%
    "importing": 0.05    # 5%
}


class ProgressService:
    """Service to track and compute upload progress across processing stages."""

    def __init__(self, db: AsyncSession, company_id: str):
        """
        Initialize ProgressService.

        Args:
            db: Database session
            company_id: Scope queries to this company
        """
        self.db = db
        self.company_id = company_id

    async def get_upload_progress(self, upload_id: str) -> Optional[UploadProgressResponse]:
        """
        Retrieve and compute real-time progress details for an upload.

        Args:
            upload_id: Unique upload identifier

        Returns:
            UploadProgressResponse or None if not found
        """
        result = await self.db.execute(
            select(UploadProgress).where(
                UploadProgress.id == upload_id,
                UploadProgress.company_id == self.company_id
            )
        )
        upload = result.scalar_one_or_none()
        if not upload:
            return None

        stage_progress = self.calculate_stage_progress(upload)
        overall_progress = self.calculate_overall_progress(upload, stage_progress)
        eta = self.calculate_eta(upload)

        # Convert to response schema
        # Ensure created_at and updated_at have timezone info or default
        started_at = upload.created_at
        if started_at and started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)

        updated_at = upload.updated_at
        if updated_at and updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)

        return UploadProgressResponse(
            upload_id=upload.id,
            status=upload.status,
            current_stage=upload.current_stage,
            stage_progress=stage_progress,
            overall_progress=overall_progress,
            processed_rows=upload.processed_rows,
            total_rows=upload.total_rows,
            error_count=upload.error_count,
            warning_count=upload.warning_count,
            estimated_completion=eta,
            started_at=started_at or datetime.now(timezone.utc),
            updated_at=updated_at
        )

    async def get_multiple_statuses(self, upload_ids: List[str]) -> MultipleUploadStatusesResponse:
        """
        Retrieve summary status details for multiple upload IDs.

        Args:
            upload_ids: List of upload identifiers

        Returns:
            MultipleUploadStatusesResponse
        """
        if not upload_ids:
            return MultipleUploadStatusesResponse(uploads=[])

        result = await self.db.execute(
            select(UploadProgress).where(
                UploadProgress.id.in_(upload_ids),
                UploadProgress.company_id == self.company_id
            )
        )
        uploads = result.scalars().all()

        items = []
        for upload in uploads:
            stage_progress = self.calculate_stage_progress(upload)
            overall_progress = self.calculate_overall_progress(upload, stage_progress)
            items.append(
                UploadStatusItem(
                    upload_id=upload.id,
                    status=upload.status,
                    current_stage=upload.current_stage,
                    overall_progress=overall_progress
                )
            )

        return MultipleUploadStatusesResponse(uploads=items)

    async def get_upload_summary(self, upload_id: str) -> Optional[UploadSummaryResponse]:
        """
        Generate a post-processing summary for a completed or terminated upload.

        Args:
            upload_id: Unique upload identifier

        Returns:
            UploadSummaryResponse or None if not found
        """
        result = await self.db.execute(
            select(UploadProgress).where(
                UploadProgress.id == upload_id,
                UploadProgress.company_id == self.company_id
            )
        )
        upload = result.scalar_one_or_none()
        if not upload:
            return None

        # Calculate processing duration
        duration_str = None
        if upload.created_at and upload.completed_at:
            # Handle timezone differences safely
            created = upload.created_at.replace(tzinfo=timezone.utc) if upload.created_at.tzinfo is None else upload.created_at
            completed = upload.completed_at.replace(tzinfo=timezone.utc) if upload.completed_at.tzinfo is None else upload.completed_at
            diff = completed - created
            duration_str = self.format_duration(int(diff.total_seconds()))

        stage_durations = self.get_stage_durations(upload)

        upload_date = upload.created_at.replace(tzinfo=timezone.utc) if upload.created_at and upload.created_at.tzinfo is None else upload.created_at

        return UploadSummaryResponse(
            upload_id=upload.id,
            file_name=upload.file_name,
            file_size=upload.file_size,
            file_type=upload.file_type,
            upload_date=upload_date or datetime.now(timezone.utc),
            processing_duration=duration_str,
            status=upload.status,
            row_count=upload.total_rows,
            error_count=upload.error_count,
            warning_count=upload.warning_count,
            stages=stage_durations
        )

    def get_active_stage(self, status: str, current_stage: Optional[str]) -> str:
        """Map DB upload status and stage string to active progress stage."""
        status_lower = status.lower()
        
        if status_lower == "completed":
            return "completed"
        if status_lower == "failed":
            if current_stage == "parse" or status_lower == "parsing":
                return "parsing"
            elif current_stage == "validate" or status_lower == "validating":
                return "validating"
            elif current_stage == "import" or status_lower == "importing":
                return "importing"
            return "validating"
        if status_lower == "cancelled":
            if current_stage == "parse":
                return "parsing"
            elif current_stage == "validate":
                return "validating"
            elif current_stage == "import":
                return "importing"
            return "validating"
        
        # Active processing mappings
        if status_lower == "uploading" or current_stage == "upload":
            return "uploading"
        if status_lower == "parsing" or current_stage == "parse":
            return "parsing"
        if status_lower == "validating" or current_stage == "validate":
            return "validating"
        if status_lower == "previewing" or current_stage == "preview":
            return "previewing"
        if status_lower == "confirmed":
            return "confirmed"
        if status_lower == "importing" or current_stage == "import":
            return "importing"
            
        return "uploading"

    def calculate_stage_progress(self, upload: UploadProgress) -> Dict[str, StageProgressDetail]:
        """Compute the progress percentage and status for each individual stage."""
        active_stage = self.get_active_stage(upload.status, upload.current_stage)
        status_lower = upload.status.lower()
        
        result = {}
        for stage in STAGE_ORDER:
            if status_lower == "completed":
                result[stage] = StageProgressDetail(percentage=100, status="completed")
            elif status_lower == "cancelled" and stage == active_stage:
                percentage = self._get_stage_percentage_estimate(stage, upload)
                result[stage] = StageProgressDetail(percentage=percentage, status="cancelled")
            elif status_lower == "failed" and stage == active_stage:
                percentage = self._get_stage_percentage_estimate(stage, upload)
                result[stage] = StageProgressDetail(percentage=percentage, status="failed")
            else:
                stage_idx = STAGE_ORDER.index(stage)
                active_idx = STAGE_ORDER.index(active_stage) if active_stage != "completed" else len(STAGE_ORDER)
                
                if stage_idx < active_idx:
                    result[stage] = StageProgressDetail(percentage=100, status="completed")
                elif stage_idx > active_idx:
                    result[stage] = StageProgressDetail(percentage=0, status="pending")
                else:
                    percentage = self._get_stage_percentage_estimate(stage, upload)
                    result[stage] = StageProgressDetail(percentage=percentage, status="in_progress")
                    
        return result

    def _get_stage_percentage_estimate(self, stage: str, upload: UploadProgress) -> int:
        """Estimate percentage progress within a specific stage."""
        overall_p = upload.progress_percentage or 0
        
        stage_offsets = {
            "uploading": (0, 20),
            "parsing": (20, 20),
            "validating": (40, 40),
            "previewing": (80, 10),
            "confirmed": (90, 5),
            "importing": (95, 5)
        }
        
        offset, weight = stage_offsets[stage]
        
        # If currently in validating stage and row counts are known, use precise calculation
        if stage == "validating" and upload.total_rows and upload.total_rows > 0:
            val_p = int((upload.processed_rows / upload.total_rows) * 100)
            return min(max(val_p, 0), 100)

        if overall_p <= offset:
            return 0
        if overall_p >= offset + weight:
            return 100
            
        fraction = (overall_p - offset) / weight
        return min(max(int(fraction * 100), 0), 100)

    def calculate_overall_progress(self, upload: UploadProgress, stage_progress: Dict[str, StageProgressDetail]) -> int:
        """Calculate aggregate overall progress percentage based on stage progress and weights."""
        status_lower = upload.status.lower()
        if status_lower == "completed":
            return 100
        if status_lower in ["failed", "cancelled"]:
            return upload.progress_percentage or 0

        overall_p = 0.0
        for stage, weight in STAGE_WEIGHTS.items():
            percentage = stage_progress[stage].percentage
            overall_p += weight * percentage
            
        return min(max(int(overall_p), 0), 100)

    def calculate_eta(self, upload: UploadProgress) -> Optional[datetime]:
        """Estimate completion time based on speed of execution so far."""
        status_lower = upload.status.lower()
        if status_lower in ["completed", "failed", "cancelled"]:
            return None

        if not upload.created_at:
            return None

        overall_p = upload.progress_percentage or 0
        if overall_p <= 0:
            return None

        # Safe time calculations
        created_at = upload.created_at.replace(tzinfo=timezone.utc) if upload.created_at.tzinfo is None else upload.created_at
        elapsed = (datetime.now(timezone.utc) - created_at).total_seconds()
        if elapsed <= 0:
            return None

        progress_rate = overall_p / elapsed
        if progress_rate <= 0:
            return None

        remaining_progress = 100 - overall_p
        eta_seconds = remaining_progress / progress_rate
        
        return datetime.now(timezone.utc) + timedelta(seconds=eta_seconds)

    def get_stage_durations(self, upload: UploadProgress) -> Dict[str, StageDuration]:
        """Format and return stage duration information from metadata."""
        meta = upload.meta_info or {}
        stage_timestamps = meta.get("stage_timestamps", {})
        
        durations = {}
        for stage in STAGE_ORDER:
            stage_times = stage_timestamps.get(stage, {})
            start_str = stage_times.get("start")
            end_str = stage_times.get("end")
            
            duration_str = None
            if start_str and end_str:
                try:
                    start = datetime.fromisoformat(start_str)
                    end = datetime.fromisoformat(end_str)
                    diff = end - start
                    duration_str = self.format_duration(int(diff.total_seconds()))
                except Exception:
                    duration_str = None
                    
            durations[stage] = StageDuration(duration=duration_str)
            
        return durations

    def format_duration(self, seconds: int) -> str:
        """Format total seconds into HH:MM:SS string representation."""
        if seconds < 0:
            seconds = 0
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
