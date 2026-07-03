"""Celery background tasks for processing file uploads."""

import asyncio
import logging
from datetime import datetime, timezone
from sqlalchemy import select

from app.tasks.celery_app import celery_app
from app.db.session import SessionLocal, engine
from app.core.redis import redis_client
from app.services.upload_service import UploadService
from app.models.upload import UploadProgress
from app.schemas.upload import UploadStatus

logger = logging.getLogger(__name__)


async def _run_upload_processing(
    upload_id: str,
    company_id: str,
    file_path: str,
    source_config_id: str,
    user_id: str
) -> None:
    """Async engine wrapper for upload processing."""
    try:
        async with SessionLocal() as db:
            upload_service = UploadService(db, company_id, user_id)
            
            logger.info(f"Starting async file processing for upload {upload_id}")
            await upload_service.process_upload_file_async(
                upload_id=upload_id,
                file_path=file_path
            )
            
    except Exception as e:
        logger.error(f"Error processing background upload {upload_id}: {str(e)}")
        # Attempt to mark the upload as failed in the database
        try:
            async with SessionLocal() as db:
                result = await db.execute(
                    select(UploadProgress).where(UploadProgress.id == upload_id)
                )
                upload = result.scalar_one_or_none()
                if upload and upload.status not in [UploadStatus.COMPLETED.value, UploadStatus.FAILED.value, UploadStatus.CANCELLED.value]:
                    upload.status = UploadStatus.FAILED.value
                    upload.error_message = f"Background processing error: {str(e)}"
                    upload.completed_at = datetime.now(timezone.utc)
                    upload.updated_at = datetime.now(timezone.utc)
                    await db.commit()
                    logger.info(f"Updated status to FAILED for upload {upload_id} in error handler")
        except Exception as db_err:
            logger.error(f"Failed to update failed status in DB for upload {upload_id}: {str(db_err)}")
        raise e
    finally:
        # Celery runs each task in a fresh asyncio.run() loop; the module-level async
        # engine and Redis client bind their connections to the loop that created them.
        # Dispose both so the next task reconnects on its own loop instead of reusing
        # connections bound to a now-closed loop (prefork = one task per process).
        await engine.dispose()
        try:
            await redis_client.aclose()
        except AttributeError:  # redis-py < 5.0.1
            await redis_client.close()


@celery_app.task(name="upload.process", bind=True, max_retries=3)
def process_upload_task(
    self,
    upload_id: str,
    company_id: str,
    file_path: str,
    source_config_id: str,
    user_id: str
):
    """Celery task for background processing of file uploads."""
    logger.info(f"Received celery task {self.request.id} for upload {upload_id}")
    try:
        return asyncio.run(
            _run_upload_processing(
                upload_id=upload_id,
                company_id=company_id,
                file_path=file_path,
                source_config_id=source_config_id,
                user_id=user_id
            )
        )
    except Exception as exc:
        # Retry logic for transient failures (e.g. database connection issues)
        # Note: If it's a validation error or ValueError, don't retry.
        if isinstance(exc, (ValueError, TypeError)):
            logger.error(f"Fatal task error for upload {upload_id}, not retrying: {str(exc)}")
            raise exc
        
        logger.warning(f"Retrying task for upload {upload_id} due to exception: {str(exc)}")
        raise self.retry(exc=exc, countdown=60)


async def _run_import_processing(
    upload_id: str,
    company_id: str,
    user_id: str
) -> None:
    """Async engine wrapper for final database import."""
    try:
        async with SessionLocal() as db:
            from app.services.import_engine import ImportEngine
            engine_service = ImportEngine(db, company_id)
            logger.info(f"Starting async import execution for upload {upload_id}")
            await engine_service.execute_import(upload_id, user_id)
            
    except Exception as e:
        logger.error(f"Error executing background import {upload_id}: {str(e)}")
        # Attempt to mark the upload as failed in the database
        try:
            async with SessionLocal() as db:
                result = await db.execute(
                    select(UploadProgress).where(UploadProgress.id == upload_id)
                )
                upload = result.scalar_one_or_none()
                if upload and upload.status not in ["completed", "failed", "cancelled"]:
                    upload.status = "failed"
                    upload.error_message = f"Import failed: {str(e)}"
                    upload.completed_at = datetime.now(timezone.utc)
                    upload.updated_at = datetime.now(timezone.utc)
                    await db.commit()
        except Exception as db_err:
            logger.error(f"Failed to update failed status in DB for import {upload_id}: {str(db_err)}")
        raise e
    finally:
        await engine.dispose()
        try:
            await redis_client.aclose()
        except AttributeError:
            await redis_client.close()


@celery_app.task(name="import.execute", bind=True, max_retries=2)
def process_import_task(
    self,
    upload_id: str,
    company_id: str,
    user_id: str
):
    """Celery task for database batch importing."""
    logger.info(f"Received celery task {self.request.id} for import {upload_id}")
    try:
        return asyncio.run(
            _run_import_processing(
                upload_id=upload_id,
                company_id=company_id,
                user_id=user_id
            )
        )
    except Exception as exc:
        if isinstance(exc, (ValueError, TypeError)):
            logger.error(f"Fatal import task error for upload {upload_id}, not retrying: {str(exc)}")
            raise exc
        logger.warning(f"Retrying import task for upload {upload_id} due to exception: {str(exc)}")
        raise self.retry(exc=exc, countdown=30)
