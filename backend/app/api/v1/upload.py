"""Upload endpoints for file upload with security validation and progress tracking."""

import os
import logging
try:
    import magic  # python-magic for MIME type detection
    MAGIC_AVAILABLE = True
except ImportError:
    logger = logging.getLogger(__name__)
    logger.warning("python-magic not available, MIME type detection will be limited")
    MAGIC_AVAILABLE = False

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from io import StringIO
import csv

from app.db.session import get_db
from app.core.deps import min_role, CurrentUser
from app.core.config import settings
from app.schemas.upload import (
    UploadRequest, UploadResponse, UploadStatusResponse, UploadErrorsResponse,
    UploadErrorDetail, UploadListResponse, UploadHistoryResponse,
    ErrorResponse, FileUploadErrorResponse, UploadStatus
)
from app.services.upload_service import (
    UploadService, sanitize_filename, save_upload_file_temporarily
)
from app.services.file_detector import FileDetector, FileDetectionResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/import", tags=["upload"])

# Constants for file validation
ALLOWED_MIME_TYPES = {
    "csv": ["text/csv", "application/csv"],
    "xlsx": ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
             "application/octet-stream"],
    "xls": ["application/vnd.ms-excel", "application/octet-stream"],
    "json": ["application/json", "text/plain"]
}

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".json"}


def validate_mime_type(file_content: bytes, declared_type: str) -> tuple[bool, Optional[str]]:
    """
    Validate MIME type matches declared format.

    Args:
        file_content: First bytes of file for magic detection
        declared_type: Declared file type

    Returns:
        Tuple of (is_valid, detected_mime_type)
    """
    if not MAGIC_AVAILABLE:
        logger.warning("MIME type detection not available, skipping validation")
        return True, None

    try:
        detected_mime = magic.from_buffer(file_content, mime=True)
        allowed_mimes = ALLOWED_MIME_TYPES.get(declared_type, [])

        # Check if detected MIME is in allowed list
        is_valid = detected_mime in allowed_mimes

        # Special handling for application/octet-stream
        if detected_mime == "application/octet-stream":
            # For office files, this might be acceptable
            is_valid = declared_type in ["xlsx", "xls"]

        return is_valid, detected_mime
    except Exception as e:
        logger.warning(f"MIME type detection failed: {str(e)}")
        # If detection fails, allow but log warning
        return True, None


def validate_file_size(file_size: int) -> bool:
    """
    Validate file size against limits.

    Args:
        file_size: File size in bytes

    Returns:
        True if file size is acceptable
    """
    if file_size > settings.UPLOAD_MAX_FILE_SIZE_HARD:
        return False

    # Check against default limit (can be overridden per company in future)
    if file_size > settings.UPLOAD_MAX_FILE_SIZE:
        logger.warning(f"File size {file_size} exceeds default limit of {settings.UPLOAD_MAX_FILE_SIZE}")

    return True


def get_file_extension(filename: str) -> Optional[str]:
    """
    Get file extension from filename.

    Args:
        filename: Filename to extract extension from

    Returns:
        Extension with dot (e.g., ".csv") or None
    """
    _, ext = os.path.splitext(filename.lower())
    return ext if ext in ALLOWED_EXTENSIONS else None


async def validate_upload_file(
    file: UploadFile,
    file_content: bytes
) -> tuple[bool, Optional[str], list[str], list[str]]:
    """
    Validate uploaded file for security and format compliance.

    Args:
        file: Uploaded file object
        file_content: File content as bytes

    Returns:
        Tuple of (is_valid, file_type, errors, warnings)
    """
    errors = []
    warnings = []

    # 1. Check filename
    if not file.filename:
        errors.append("No filename provided")
        return False, None, errors, warnings

    # 2. Check file extension
    file_ext = get_file_extension(file.filename)
    if not file_ext:
        errors.append(f"Invalid file extension. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")
        return False, None, errors, warnings

    file_type = file_ext.lstrip('.')

    # 3. Check file size
    file_size = len(file_content)
    if file_size == 0:
        errors.append("File is empty")
        return False, file_type, errors, warnings

    if not validate_file_size(file_size):
        errors.append(
            f"File size ({file_size} bytes) exceeds maximum allowed size "
            f"({settings.UPLOAD_MAX_FILE_SIZE_HARD} bytes)"
        )
        return False, file_type, errors, warnings

    # 4. Validate MIME type using magic bytes
    is_valid_mime, detected_mime = validate_mime_type(file_content[:2048], file_type)
    if not is_valid_mime:
        errors.append(
            f"File format mismatch. Declared: {file_type}, Detected: {detected_mime}. "
            f"File may be corrupted or have incorrect extension."
        )
        return False, file_type, errors, warnings

    if detected_mime and detected_mime not in ALLOWED_MIME_TYPES.get(file_type, []):
        warnings.append(
            f"Detected MIME type ({detected_mime}) doesn't match expected type for .{file_type}"
        )

    # 5. Additional format-specific validation (Commented out per senior requirement)
    # try:
    #     detection_result = FileDetector.detect_file_from_content(file_content, file_type)
    #     if detection_result.error:
    #         warnings.append(detection_result.error)
    #     if not detection_result.is_valid:
    #         errors.append(f"File format validation failed: {detection_result.error}")
    #         return False, file_type, errors, warnings
    # except Exception as e:
    #     logger.warning(f"File detection failed: {str(e)}")
    #     warnings.append(f"Could not perform detailed file validation: {str(e)}")

    logger.info(
        f"File validation passed: {file.filename} ({file_type}, {file_size} bytes, MIME: {detected_mime})"
    )

    return True, file_type, errors, warnings


@router.post(
    "/sources/{source_id}/data-upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload data file for processing",
    description="Upload a CSV, Excel, or JSON file for parsing and validation. Returns upload ID for tracking progress."
)
async def upload_file(
    source_id: str,
    file: UploadFile = File(..., description="Data file to upload (CSV, Excel, or JSON)"),
    validate_immediately: bool = Form(True, description="Whether to validate immediately after upload"),
    async_processing: bool = Form(False, description="Whether to use async processing"),
    source_type: Optional[str] = Form("transaction", description="Type of data source"),
    user: CurrentUser = Depends(min_role("planner")),
    db: AsyncSession = Depends(get_db)
):
    """
    Upload a data file for processing.

    - **file**: The data file (CSV, Excel, or JSON)
    - **validate_immediately**: Whether to validate immediately (default: true)
    - **async_processing**: Whether to use async processing (default: false)
    - **source_type**: Type of data source (default: "transaction")

    Returns upload ID for tracking progress via status endpoint.
    """
    logger.info(
        f"File upload request: user={user.id}, source={source_id}, "
        f"file={file.filename}, validate={validate_immediately}, async={async_processing}"
    )

    # Read file content
    try:
        file_content = await file.read()
        logger.info(f"Read {len(file_content)} bytes from uploaded file")
    except Exception as e:
        logger.error(f"Failed to read uploaded file: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read uploaded file: {str(e)}"
        )

    # Validate file
    is_valid, file_type, errors, warnings = await validate_upload_file(file, file_content)

    if not is_valid:
        logger.warning(f"File validation failed: {errors}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "detail": "File validation failed",
                "error_code": "INVALID_FILE",
                "errors": errors,
                "warnings": warnings,
                "file_name": file.filename,
                "allowed_types": list(ALLOWED_EXTENSIONS)
            }
        )

    # Log warnings if any
    if warnings:
        logger.warning(f"File upload warnings: {warnings}")

    # Save file temporarily
    try:
        temp_file_path = save_upload_file_temporarily(file_content, file.filename)
        logger.info(f"Saved temporary file: {temp_file_path}")
    except Exception as e:
        logger.error(f"Failed to save temporary file: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save uploaded file: {str(e)}"
        )

    # Create upload service and process
    upload_service = UploadService(db, user.company_id, user.id)

    # Determine if async processing should be triggered
    # File size >= settings.UPLOAD_MIN_ASYNC_SIZE (10MB) or async_processing requested
    is_async = async_processing or len(file_content) >= settings.UPLOAD_MIN_ASYNC_SIZE

    try:
        # Create upload record
        upload = await upload_service.create_upload(
            source_config_id=source_id,
            file_name=file.filename,
            file_size=len(file_content),
            file_type=file_type,
            validate_immediately=validate_immediately,
            async_processing=is_async,  # Store the actual processing mode (async if triggered)
            metadata={"source_type": source_type}
        )

        if is_async:
            from app.tasks.upload_tasks import process_upload_task
            from app.services.task_manager import TaskManager

            # Trigger background Celery task
            task = process_upload_task.delay(
                upload_id=upload.id,
                company_id=user.company_id,
                file_path=temp_file_path,
                source_config_id=source_id,
                user_id=user.id
            )

            # Register task ID in upload metadata
            task_manager = TaskManager(db)
            await task_manager.register_task(upload.id, task.id)
            await db.commit()

            logger.info(f"Upload {upload.id} processing in background. Task ID: {task.id}")

            return UploadResponse(
                upload_id=upload.id,
                status=UploadStatus.PENDING,
                file_name=upload.file_name,
                file_size=upload.file_size,
                file_type=upload.file_type,
                total_rows=None,
                processed_rows=0,
                error_count=0,
                warning_count=0,
                validation_result=None,
                created_at=upload.created_at,
                estimated_completion=None
            )
        else:
            # Process file synchronously (parse and optionally validate)
            result = await upload_service.process_upload_file(
                upload_id=upload.id,
                file_path=temp_file_path,
                validate_immediately=validate_immediately
            )

            logger.info(f"Upload {upload.id} processing complete: status={result.status}")

            return result

    except ValueError as e:
        logger.error(f"Upload processing error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected error during upload: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload processing failed: {str(e)}"
        )
    finally:
        # Cleanup temporary file ONLY if it was processed synchronously!
        # If it was processed asynchronously, the Celery task is responsible for deleting it.
        if not is_async:
            try:
                from sqlalchemy import select
                result_status = None
                try:
                    db_res = await db.execute(
                        select(UploadProgress.status).where(UploadProgress.id == upload.id)
                    )
                    result_status = db_res.scalar_one_or_none()
                except Exception:
                    pass
                if result_status != "awaiting_confirm":
                    await upload_service.cleanup_temp_files(temp_file_path)
            except Exception as e:
                logger.warning(f"Failed to cleanup temporary file: {str(e)}")


@router.get(
    "/uploads/{upload_id}/status",
    response_model=UploadStatusResponse,
    summary="Get upload status",
    description="Retrieve current status and progress of an upload operation."
)
async def get_upload_status(
    upload_id: str,
    user: CurrentUser = Depends(min_role("planner")),
    db: AsyncSession = Depends(get_db)
):
    """
    Get upload status and progress.

    Returns detailed information about upload progress including:
    - Current status and stage
    - Progress percentage
    - Row counts (total and processed)
    - Error and warning counts
    - Estimated completion time
    """
    upload_service = UploadService(db, user.company_id, user.id)

    status_result = await upload_service.get_upload_status(upload_id)

    if not status_result:
        logger.warning(f"Upload {upload_id} not found for user {user.id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Upload {upload_id} not found"
        )

    logger.info(f"Retrieved status for upload {upload_id}: {status_result.status}")

    return status_result


@router.post(
    "/uploads/{upload_id}/cancel",
    response_model=UploadStatusResponse,
    summary="Cancel upload processing",
    description="Cancel an in-progress upload task."
)
async def cancel_upload(
    upload_id: str,
    user: CurrentUser = Depends(min_role("planner")),
    db: AsyncSession = Depends(get_db)
):
    """
    Cancel an active upload task.
    """
    upload_service = UploadService(db, user.company_id, user.id)

    # Check upload exists and belongs to company
    status_result = await upload_service.get_upload_status(upload_id)
    if not status_result:
        logger.warning(f"Upload {upload_id} not found for user {user.id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Upload {upload_id} not found"
        )

    from app.services.task_manager import TaskManager
    task_manager = TaskManager(db)
    success = await task_manager.cancel_upload_task(upload_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload task cannot be cancelled (might be completed, failed, or already cancelled)"
        )

    # Get updated status
    updated_status = await upload_service.get_upload_status(upload_id)
    return updated_status


@router.get(
    "/uploads/{upload_id}/errors",
    response_model=UploadErrorsResponse,
    summary="Get upload errors",
    description="Retrieve validation errors for an upload with pagination and filtering."
)
async def get_upload_errors(
    upload_id: str,
    severity: Optional[str] = Query(None, description="Filter by severity (error, warning, info)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of errors to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    user: CurrentUser = Depends(min_role("planner")),
    db: AsyncSession = Depends(get_db)
):
    """
    Get validation errors for an upload.

    - **severity**: Optional filter by severity level
    - **limit**: Maximum errors to return (max 1000)
    - **offset**: Pagination offset

    Returns paginated list of errors with metadata.
    """
    upload_service = UploadService(db, user.company_id, user.id)

    # Verify upload exists and belongs to user's company
    status_result = await upload_service.get_upload_status(upload_id)
    if not status_result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Upload {upload_id} not found"
        )

    errors, total_count = await upload_service.get_upload_errors(
        upload_id=upload_id,
        severity=severity,
        limit=limit,
        offset=offset
    )

    # Count blocking errors
    blocking_errors = sum(1 for e in errors if e.is_blocking)

    # Count warnings
    total_warnings = sum(1 for e in errors if e.severity == "warning")

    # Convert to response format
    error_details = [
        UploadErrorDetail(
            row_number=error.row_number,
            column=error.column_name,
            value=error.raw_value,
            error_type=error.error_type,
            severity=error.severity,
            message=error.error_message,
            is_blocking=error.is_blocking,
            created_at=error.created_at
        )
        for error in errors
    ]

    logger.info(
        f"Retrieved {len(error_details)} errors for upload {upload_id} "
        f"(total: {total_count}, blocking: {blocking_errors})"
    )

    return UploadErrorsResponse(
        upload_id=upload_id,
        total_errors=total_count,
        blocking_errors=blocking_errors,
        total_warnings=total_warnings,
        errors=error_details,
        limit=limit,
        offset=offset,
        has_more=offset + len(error_details) < total_count
    )


@router.get(
    "/uploads/{upload_id}/errors/download",
    summary="Download validation errors as file",
    description="Download validation errors as CSV or Excel file."
)
async def download_errors(
    upload_id: str,
    format: str = Query("csv", description="Export format: csv or excel"),
    user: CurrentUser = Depends(min_role("planner")),
    db: AsyncSession = Depends(get_db)
):
    """
    Download validation errors as a file.

    - **format**: Export format (csv or excel)

    Returns file download with appropriate content type.
    """
    upload_service = UploadService(db, user.company_id, user.id)

    # Verify upload exists
    status_result = await upload_service.get_upload_status(upload_id)
    if not status_result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Upload {upload_id} not found"
        )

    # Get all errors
    errors, total_count = await upload_service.get_upload_errors(
        upload_id=upload_id,
        severity=None,
        limit=10000,  # Large limit for download
        offset=0
    )

    if not errors:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No errors found for this upload"
        )

    if format.lower() == "csv":
        # Generate CSV
        output = StringIO()
        writer = csv.writer(output)

        # Write header
        writer.writerow(["Row", "Column", "Value", "Error Type", "Severity", "Message", "Is Blocking"])

        # Write errors
        for error in errors:
            writer.writerow([
                error.row_number or "",
                error.column_name or "",
                error.raw_value or "",
                error.error_type,
                error.severity,
                error.error_message,
                "Yes" if error.is_blocking else "No"
            ])

        # Create response
        output.seek(0)
        response = StreamingResponse(
            output,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=errors_{upload_id}.csv"
            }
        )

        logger.info(f"Generated CSV download for upload {upload_id} with {len(errors)} errors")
        return response

    elif format.lower() == "excel":
        # Generate Excel file (would require openpyxl)
        # For now, return error
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Excel export not yet implemented"
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format: {format}. Use 'csv' or 'excel'"
        )


@router.get(
    "/uploads/history",
    response_model=UploadListResponse,
    summary="Get upload history",
    description="Retrieve upload history for the user's company with pagination."
)
async def get_upload_history(
    limit: int = Query(50, ge=1, le=100, description="Number of records per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    user: CurrentUser = Depends(min_role("planner")),
    db: AsyncSession = Depends(get_db)
):
    """
    Get upload history for the user's company.

    Returns paginated list of historical uploads with metadata.
    """
    upload_service = UploadService(db, user.company_id, user.id)

    history, total_count = await upload_service.get_upload_history(
        limit=limit,
        offset=offset
    )

    # Convert to response format
    history_records = [
        UploadHistoryResponse(
            upload_id=h.id,
            file_name=h.file_name,
            file_type=h.file_type,
            file_size=h.file_size,
            upload_date=h.upload_date,
            status=h.status,
            duration_seconds=h.duration_seconds,
            row_count=h.row_count,
            error_count=h.error_count,
            warning_count=h.warning_count,
            result_summary=h.result_summary
        )
        for h in history
    ]

    logger.info(
        f"Retrieved {len(history_records)} upload history records for company {user.company_id}"
    )

    return UploadListResponse(
        uploads=history_records,
        total_count=total_count,
        page=offset // limit + 1,
        page_size=limit,
        has_more=offset + len(history_records) < total_count
    )


@router.delete(
    "/uploads/{upload_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete upload record and dataset from database",
    description="Removes associated target table rows, progress tracking status, and audit history logs."
)
async def delete_upload(
    upload_id: str,
    user: CurrentUser = Depends(min_role("planner")),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete upload records and data from database.
    """
    logger.info(f"Delete upload request: user={user.id}, upload_id={upload_id}")
    
    from app.models import DataUpload, SourceConfig
    from app.models.upload import UploadProgress, UploadHistory
    from sqlalchemy import delete, select
    
    # 1. Fetch tracking records to determine file type/category
    up_record = (await db.execute(
        select(UploadProgress).where(UploadProgress.id == upload_id, UploadProgress.company_id == user.company_id)
    )).scalar_one_or_none()
    
    uh_record = (await db.execute(
        select(UploadHistory).where(UploadHistory.id == upload_id, UploadHistory.company_id == user.company_id)
    )).scalar_one_or_none()
    
    record = up_record or uh_record
    source_type = None
    
    if record:
        meta = getattr(record, "meta_info", {}) or {}
        staged_file = meta.get("staged_file_path")
        if staged_file and os.path.exists(staged_file):
            try:
                os.remove(staged_file)
                logger.info(f"Deleted temporary staging file from disk: {staged_file}")
            except Exception as e:
                logger.warning(f"Failed to delete temporary staging file {staged_file}: {str(e)}")
        
        summary = getattr(record, "result_summary", {}) or {}
        source_type = meta.get("source_type") or summary.get("source_type")
        
        # Fallback to SourceConfig if config exists
        if not source_type and record.source_config_id:
            sc_record = (await db.execute(
                select(SourceConfig).where(SourceConfig.id == record.source_config_id)
            )).scalar_one_or_none()
            if sc_record:
                source_type = sc_record.file_type
                
        # Final fallback: guess from filename
        if not source_type and record.file_name:
            fn = str(record.file_name).lower()
            if "calendar" in fn:
                source_type = "calendar"
            elif "price" in fn:
                source_type = "sell_prices"
            elif "lookup" in fn or "master" in fn:
                source_type = "lookup"
            elif "sales" in fn:
                source_type = "sales"

    # 2. Clear target tables if category matches
    if source_type:
        source_type_lower = source_type.lower()
        if source_type_lower == "calendar":
            from app.models import Calendar
            logger.info(f"Clearing Calendar table for company {user.company_id}")
            await db.execute(delete(Calendar).where(Calendar.company_id == user.company_id))
            
        elif source_type_lower in ("sell_prices", "sell_price"):
            from app.models import SellPrice
            logger.info(f"Clearing SellPrice table for company {user.company_id}")
            await db.execute(delete(SellPrice).where(SellPrice.company_id == user.company_id))
            
        elif source_type_lower == "sales":
            from app.models import Sales
            logger.info(f"Clearing Sales table for company {user.company_id}")
            await db.execute(delete(Sales).where(Sales.company_id == user.company_id))
            
        elif source_type_lower == "lookup":
            from app.models import Lookup
            logger.info(f"Clearing Lookup table for company {user.company_id}")
            await db.execute(delete(Lookup).where(Lookup.company_id == user.company_id))

        elif source_type_lower == "actuals":
            from app.models import Actual
            session_id = meta.get("session_id")
            if session_id:
                logger.info(f"Clearing Actual records for session {session_id} and company {user.company_id}")
                await db.execute(delete(Actual).where(Actual.company_id == user.company_id, Actual.session_id == session_id))
            else:
                logger.info(f"Clearing all Actual records for company {user.company_id}")
                await db.execute(delete(Actual).where(Actual.company_id == user.company_id))

    # 3. Clean up the tracking records
    await db.execute(delete(DataUpload).where(DataUpload.id == upload_id, DataUpload.company_id == user.company_id))
    await db.execute(delete(UploadProgress).where(UploadProgress.id == upload_id, UploadProgress.company_id == user.company_id))
    await db.execute(delete(UploadHistory).where(UploadHistory.id == upload_id, UploadHistory.company_id == user.company_id))
    
    await db.commit()
    logger.info(f"Successfully deleted upload_id={upload_id} and cleared its target data.")
