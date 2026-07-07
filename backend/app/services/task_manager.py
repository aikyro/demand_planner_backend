"""Service for managing Celery tasks and task lifecycle."""

import logging
import os
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.upload import UploadProgress
from app.schemas.upload import UploadStatus
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


class TaskManager:
    """Service for managing background Celery tasks and cancellation."""

    def __init__(self, db: AsyncSession):
        """
        Initialize TaskManager.

        Args:
            db: Database session
        """
        self.db = db

    async def register_task(self, upload_id: str, celery_task_id: str) -> None:
        """
        Register a Celery task ID in the upload progress metadata.

        Args:
            upload_id: Upload identifier
            celery_task_id: Celery task identifier
        """
        result = await self.db.execute(
            select(UploadProgress).where(UploadProgress.id == upload_id)
        )
        upload = result.scalar_one_or_none()
        
        if upload:
            meta = dict(upload.meta_info) if upload.meta_info else {}
            meta["task_id"] = celery_task_id
            upload.meta_info = meta
            await self.db.flush()
            logger.info(f"Registered celery task {celery_task_id} for upload {upload_id}")
        else:
            logger.warning(f"Could not register task {celery_task_id}: upload {upload_id} not found")

    async def cancel_upload_task(self, upload_id: str) -> bool:
        """
        Cancel a running upload task.
        Marks it as cancelled in the database and revokes the Celery task.

        Args:
            upload_id: Upload identifier

        Returns:
            True if cancelled successfully, False otherwise
        """
        result = await self.db.execute(
            select(UploadProgress).where(UploadProgress.id == upload_id)
        )
        upload = result.scalar_one_or_none()
        
        if not upload:
            logger.warning(f"Upload {upload_id} not found for cancellation")
            return False

        if upload.status in [UploadStatus.COMPLETED.value, UploadStatus.FAILED.value, UploadStatus.CANCELLED.value]:
            logger.warning(f"Upload {upload_id} is already in terminal state: {upload.status}")
            return False

        # Mark as cancelled in database
        upload.status = UploadStatus.CANCELLED.value
        upload.current_stage = None
        upload.completed_at = datetime.now(timezone.utc)
        upload.updated_at = datetime.now(timezone.utc)
        await self.db.flush()

        # Revoke Celery task if present in metadata
        celery_task_id = upload.meta_info.get("task_id")
        if celery_task_id:
            logger.info(f"Revoking celery task {celery_task_id} for upload {upload_id}")
            celery_app.control.revoke(celery_task_id, terminate=True)
        else:
            logger.warning(f"Celery task ID not found in metadata for upload {upload_id}")

        # Remove the staged file from /tmp/uploads/ — the user explicitly
        # cancelled, so it should not be retained. Best-effort: if the file
        # was never written (POST aborted) or already cleaned up by the
        # worker, just log and move on.
        staged_file_path = (upload.meta_info or {}).get("staged_file_path")
        if staged_file_path:
            try:
                if os.path.exists(staged_file_path):
                    os.remove(staged_file_path)
                    logger.info(
                        f"Removed staged file after cancellation: {staged_file_path}"
                    )
            except Exception as e:
                logger.warning(
                    f"Failed to remove staged file {staged_file_path}: {e}"
                )

        await self.db.commit()
        return True
