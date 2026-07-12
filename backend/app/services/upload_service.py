"""Upload orchestration service integrating parser and validation with progress tracking."""

import os
import tempfile
import shutil
import uuid
import logging
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta, timezone
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.models.upload import UploadProgress, ValidationError, UploadHistory
from app.schemas.upload import (
    UploadStatus, FileType, UploadResponse, UploadStatusResponse,
    UploadProgressUpdate, UploadHistoryResponse
)
from app.schemas.validation import ValidationResult, ValidationConfig
from app.schemas.files import ParseResult
from app.services.file_parser import FileParser
from app.services.validation_service import ValidationService
from app.core.config import settings

logger = logging.getLogger(__name__)


class UploadService:
    """
    Service for orchestrating file upload, parsing, and validation.
    Integrates with file parser and validation services while tracking progress.
    """

    def __init__(self, db: AsyncSession, company_id: str, user_id: str):
        """
        Initialize upload service.

        Args:
            db: Database session
            company_id: Company identifier for scoping
            user_id: User identifier for tracking
        """
        self.db = db
        self.company_id = company_id
        self.user_id = user_id
        self.file_parser = FileParser(
            chunk_size=settings.PARSER_CHUNK_SIZE,
            sample_size=settings.PARSER_SAMPLE_SIZE,
            max_memory_mb=settings.PARSER_MAX_MEMORY_MB
        )
        self.validation_config = ValidationConfig(
            max_errors_to_display=settings.VALIDATION_MAX_ERRORS_DISPLAY,
            warning_threshold=settings.VALIDATION_WARNING_THRESHOLD,
            batch_size=settings.VALIDATION_BATCH_SIZE,
            stop_on_first_error=settings.VALIDATION_STOP_ON_FIRST_ERROR,
            enable_schema_validation=settings.VALIDATION_ENABLE_SCHEMA,
            enable_business_rules=settings.VALIDATION_ENABLE_BUSINESS_RULES,
            enable_data_quality=settings.VALIDATION_ENABLE_DATA_QUALITY,
            duplicate_threshold=settings.VALIDATION_DUPLICATE_THRESHOLD,
            outlier_std_dev=settings.VALIDATION_OUTLIER_STD_DEV,
            missing_value_threshold=settings.VALIDATION_MISSING_VALUE_THRESHOLD,
            revenue_tolerance=settings.VALIDATION_REVENUE_TOLERANCE,
            allow_future_dates=settings.VALIDATION_ALLOW_FUTURE_DATES,
            min_quantity=settings.VALIDATION_MIN_QUANTITY,
            max_quantity=settings.VALIDATION_MAX_QUANTITY,
            min_price=settings.VALIDATION_MIN_PRICE,
            max_price=settings.VALIDATION_MAX_PRICE,
            parallel_processing=settings.VALIDATION_PARALLEL_PROCESSING
        )
        self.validation_service = ValidationService(self.validation_config)

    async def create_upload(
        self,
        source_config_id: str,
        file_name: str,
        file_size: int,
        file_type: str,
        validate_immediately: bool = True,
        async_processing: bool = False,
        metadata: Optional[Dict[str, Any]] = None
    ) -> UploadProgress:
        """
        Create a new upload progress record.

        Args:
            source_config_id: Source configuration identifier
            file_name: Name of uploaded file
            file_size: Size of file in bytes
            file_type: Type of file (csv, xlsx, xls, json)
            validate_immediately: Whether to validate immediately
            async_processing: Whether to use async processing
            metadata: Additional metadata

        Returns:
            UploadProgress instance
        """
        upload = UploadProgress(
            id=str(uuid.uuid4()),
            company_id=self.company_id,
            source_config_id=source_config_id,
            user_id=self.user_id,
            status=UploadStatus.UPLOADING.value,
            current_stage="upload",
            progress_percentage=10,
            file_size=file_size,
            file_name=file_name,
            file_type=file_type,
            meta_info=metadata or {}
        )

        self._update_stage_timestamp(upload, "uploading", "start")
        self.db.add(upload)
        await self.db.flush()

        logger.info(
            f"Created upload {upload.id} for source {source_config_id}, "
            f"file {file_name} ({file_size} bytes)"
        )

        return upload

    async def update_upload_progress(
        self,
        upload_id: str,
        update: UploadProgressUpdate
    ) -> Optional[UploadProgress]:
        """
        Update upload progress.

        Args:
            upload_id: Upload identifier
            update: Progress update data

        Returns:
            Updated UploadProgress or None if not found
        """
        result = await self.db.execute(
            select(UploadProgress).where(
                UploadProgress.id == upload_id,
                UploadProgress.company_id == self.company_id
            )
        )
        upload = result.scalar_one_or_none()

        if not upload:
            logger.warning(f"Upload {upload_id} not found for company {self.company_id}")
            return None

        # Update fields that are provided
        if update.status:
            upload.status = update.status.value
        if update.current_stage:
            upload.current_stage = update.current_stage
        if update.progress_percentage is not None:
            upload.progress_percentage = update.progress_percentage
        if update.total_rows is not None:
            upload.total_rows = update.total_rows
        if update.processed_rows is not None:
            upload.processed_rows = update.processed_rows
        if update.error_count is not None:
            upload.error_count = update.error_count
        if update.warning_count is not None:
            upload.warning_count = update.warning_count
        if update.error_message:
            upload.error_message = update.error_message

        upload.updated_at = datetime.now(timezone.utc)

        # Set completed_at if status is terminal
        if update.status in [UploadStatus.COMPLETED, UploadStatus.FAILED, UploadStatus.CANCELLED]:
            upload.completed_at = datetime.now(timezone.utc)

        await self.db.flush()

        logger.info(f"Updated upload {upload_id} progress to {upload.progress_percentage}%")

        return upload

    async def get_upload_status(self, upload_id: str) -> Optional[UploadStatusResponse]:
        """
        Get upload status.

        Args:
            upload_id: Upload identifier

        Returns:
            UploadStatusResponse or None if not found
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

        # Estimate completion time for in-progress uploads
        estimated_completion = None
        if upload.status not in [UploadStatus.COMPLETED.value, UploadStatus.FAILED.value, UploadStatus.CANCELLED.value]:
            if upload.progress_percentage > 0 and upload.processed_rows > 0:
                # Calculate rate: rows processed since creation
                time_since_start = (datetime.now(timezone.utc) - upload.created_at).total_seconds()
                if time_since_start > 0 and upload.total_rows:
                    rows_per_second = upload.processed_rows / time_since_start
                    remaining_rows = upload.total_rows - upload.processed_rows
                    if rows_per_second > 0:
                        remaining_seconds = remaining_rows / rows_per_second
                        estimated_completion = datetime.now(timezone.utc) + timedelta(seconds=remaining_seconds)

        return UploadStatusResponse(
            upload_id=upload.id,
            status=UploadStatus(upload.status),
            current_stage=upload.current_stage,
            progress_percentage=upload.progress_percentage,
            total_rows=upload.total_rows,
            processed_rows=upload.processed_rows,
            error_count=upload.error_count,
            warning_count=upload.warning_count,
            created_at=upload.created_at,
            updated_at=upload.updated_at,
            completed_at=upload.completed_at,
            estimated_completion=estimated_completion,
            error_message=upload.error_message
        )

    async def process_upload_file(
        self,
        upload_id: str,
        file_path: str,
        validate_immediately: bool = True
    ) -> UploadResponse:
        """
        Process uploaded file: parse and optionally validate.

        Args:
            upload_id: Upload identifier
            file_path: Path to uploaded file
            validate_immediately: Whether to validate after parsing

        Returns:
            UploadResponse with processing results

        Raises:
            ValueError: If upload not found or file processing fails
        """
        # Get upload
        result = await self.db.execute(
            select(UploadProgress).where(
                UploadProgress.id == upload_id,
                UploadProgress.company_id == self.company_id
            )
        )
        upload = result.scalar_one_or_none()

        if not upload:
            raise ValueError(f"Upload {upload_id} not found")

        try:
            # Update status to parsing
            upload.status = UploadStatus.PARSING.value
            upload.current_stage = "parse"
            upload.progress_percentage = 20
            self._update_stage_timestamp(upload, "uploading", "end")
            self._update_stage_timestamp(upload, "parsing", "start")
            await self.db.flush()

            # Parse file
            logger.info(f"Parsing file {file_path} for upload {upload_id}")
            parse_result = self.file_parser.parse_file(
                file_path=file_path
            )

            # Update upload with parsing results
            upload.total_rows = parse_result.metadata.total_rows or 0
            upload.processed_rows = parse_result.metadata.total_rows or 0
            upload.progress_percentage = 50

            if parse_result.error_count > 0:
                upload.error_count = parse_result.error_count
                # Store parsing errors as simple validation errors
                for error_msg in parse_result.errors:
                    validation_error = ValidationError(
                        id=str(uuid.uuid4()),
                        upload_progress_id=upload.id,
                        row_number=None,  # Parse errors don't have row numbers
                        column_name=None,  # Parse errors don't have column names
                        raw_value=None,
                        error_type="parsing",
                        error_category="parse_error",
                        error_message=error_msg,
                        severity="error",
                        is_blocking=True,
                        error_metadata={},
                        created_at=datetime.now(timezone.utc)
                    )
                    self.db.add(validation_error)

            self._update_stage_timestamp(upload, "parsing", "end")
            await self.db.flush()

            # Validate if requested
            validation_result_dict = None
            if validate_immediately and parse_result.sample_data:
                upload.status = UploadStatus.VALIDATING.value
                upload.current_stage = "validate"
                upload.progress_percentage = 60
                self._update_stage_timestamp(upload, "validating", "start")
                await self.db.flush()

                validation_result = await self._validate_data(
                    upload_id, parse_result.sample_data
                )

                # Update upload with validation results
                upload.error_count = validation_result.statistics.total_errors
                upload.warning_count = validation_result.statistics.total_warnings
                upload.progress_percentage = 90

                # Store validation errors
                for error in validation_result.errors:
                    # Map error types to allowed database values
                    error_type_map = {
                        "validation_error": "validation",
                        "business_rule": "business_rule",
                        "data_quality": "validation",
                        "parsing_error": "parsing",
                        "system_error": "system"
                    }
                    error_type_value = error_type_map.get(
                        error.error_type.value, "validation"
                    )

                    validation_error = ValidationError(
                        id=str(uuid.uuid4()),
                        upload_progress_id=upload.id,
                        row_number=error.row_number,
                        column_name=error.column_name,
                        raw_value=error.raw_value,
                        error_type=error_type_value,
                        error_category=error.error_category.value,
                        error_message=error.error_message,
                        severity=error.severity.value,
                        is_blocking=error.is_blocking,
                        error_metadata=error.meta_info,
                        created_at=error.created_at
                    )
                    self.db.add(validation_error)

                validation_result_dict = {
                    "is_valid": validation_result.is_valid,
                    "can_import": validation_result.can_import,
                    "total_errors": validation_result.statistics.total_errors,
                    "total_warnings": validation_result.statistics.total_warnings,
                    "blocking_errors": validation_result.statistics.blocking_errors
                }

                self._update_stage_timestamp(upload, "validating", "end")
                await self.db.flush()

            # Generate and save preview / summary / mapping data for sync upload
            column_names = list(parse_result.sample_data[0].keys()) if (parse_result and parse_result.sample_data) else []
            from app.services.preview_service import StreamingSummaryCalculator
            summary_calc = StreamingSummaryCalculator(column_names)
            summary_calc.process_chunk(parse_result.sample_data or [])
            summary = summary_calc.get_summary(
                file_size=upload.file_size or 0,
                file_type=upload.file_type or "csv",
                encoding="UTF-8"
            )
            source_type = upload.meta_info.get("source_type", "transaction") if upload.meta_info else "transaction"
            self._save_preview_and_mapping(
                upload=upload,
                first_rows=parse_result.sample_data or [],
                last_rows=parse_result.sample_data or [],
                summary=summary,
                source_type=source_type,
                column_names=column_names
            )

            # Mark as awaiting_confirm
            if not validate_immediately or validation_result_dict.get("is_valid", True):
                upload.status = "awaiting_confirm"
                upload.current_stage = "awaiting_confirm"
                upload.progress_percentage = 90
                # Save staged file path
                meta = dict(upload.meta_info) if upload.meta_info else {}
                meta["staged_file_path"] = file_path
                upload.meta_info = meta
                flag_modified(upload, "meta_info")
            else:
                upload.status = UploadStatus.FAILED.value
                upload.progress_percentage = 100
                
            upload.completed_at = datetime.now(timezone.utc)
            await self.db.flush()

            # Create history record
            await self._create_upload_history(upload)

            await self.db.commit()

            # Build response
            return UploadResponse(
                upload_id=upload.id,
                status=UploadStatus(upload.status),
                file_name=upload.file_name,
                file_size=upload.file_size,
                file_type=upload.file_type,
                total_rows=upload.total_rows,
                processed_rows=upload.processed_rows,
                error_count=upload.error_count,
                warning_count=upload.warning_count,
                validation_result=validation_result_dict,
                created_at=upload.created_at,
                estimated_completion=None
            )

        except Exception as e:
            logger.error(f"Error processing upload {upload_id}: {str(e)}")
            upload.status = UploadStatus.FAILED.value
            upload.error_message = str(e)[:2000]
            upload.progress_percentage = 0
            await self.db.commit()

            raise

    async def _validate_data(
        self,
        upload_id: str,
        data: List[Dict[str, Any]],
        source_type: str = "transaction"
    ) -> ValidationResult:
        """
        Validate parsed data.

        Args:
            upload_id: Upload identifier
            data: Parsed data rows
            source_type: The file type context (e.g. transaction, calendar, sell_prices)

        Returns:
            ValidationResult
        """
        logger.info(f"Validating {len(data)} rows for upload {upload_id}")

        def progress_callback(percentage: float, stage: str):
            """Update progress during validation."""
            # This could be enhanced to update database progress
            pass

        validation_result = self.validation_service.validate_all(
            rows=data,
            source_type=source_type,
            progress_callback=progress_callback
        )

        logger.info(
            f"Validation complete for upload {upload_id}: "
            f"{validation_result.statistics.total_errors} errors, "
            f"{validation_result.statistics.total_warnings} warnings"
        )

        return validation_result

    async def _create_upload_history(self, upload: UploadProgress) -> UploadHistory:
        """
        Create upload history record.

        Args:
            upload: UploadProgress instance

        Returns:
            UploadHistory instance
        """
        duration = None
        if upload.completed_at and upload.created_at:
            duration = int((upload.completed_at - upload.created_at).total_seconds())

        stages = {}
        meta = upload.meta_info or {}
        stage_timestamps = meta.get("stage_timestamps", {})
        for stage, times in stage_timestamps.items():
            start_str = times.get("start")
            end_str = times.get("end")
            duration_str = None
            if start_str and end_str:
                try:
                    start = datetime.fromisoformat(start_str)
                    end = datetime.fromisoformat(end_str)
                    diff = end - start
                    secs = int(diff.total_seconds())
                    hours = secs // 3600
                    mins = (secs % 3600) // 60
                    s = secs % 60
                    duration_str = f"{hours:02d}:{mins:02d}:{s:02d}"
                except Exception:
                    duration_str = None
            stages[stage] = {
                "duration": duration_str,
                "status": "completed" if end_str else "failed"
            }

        # Extract columns list and source type
        summary_meta = meta.get("summary") or {}
        columns = list(summary_meta.get("column_types", {}).keys())
        if not columns and meta.get("preview_data", {}).get("first_rows"):
            columns = list(meta["preview_data"]["first_rows"][0].keys())

        history = UploadHistory(
            id=str(uuid.uuid4()),
            company_id=upload.company_id,
            user_id=upload.user_id,
            source_config_id=upload.source_config_id,
            file_name=upload.file_name,
            file_type=upload.file_type,
            file_size=upload.file_size,
            upload_date=upload.created_at,
            status=upload.status,
            duration_seconds=duration,
            row_count=upload.total_rows,
            error_count=upload.error_count,
            warning_count=upload.warning_count,
            result_summary={
                "processed_rows": upload.processed_rows,
                "error_message": upload.error_message,
                "stages": stages,
                "columns": columns,
                "source_type": meta.get("source_type"),
                "session_id": meta.get("session_id")
            }
        )

        self.db.add(history)
        await self.db.flush()

        logger.info(f"Created upload history {history.id} for upload {upload.id}")

        return history

    async def get_upload_errors(
        self,
        upload_id: str,
        severity: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> tuple[List[ValidationError], int]:
        """
        Get validation errors for an upload.

        Args:
            upload_id: Upload identifier
            severity: Filter by severity (error, warning, info)
            limit: Maximum number of errors to return
            offset: Offset for pagination

        Returns:
            Tuple of (errors list, total count)
        """
        # Build query
        from sqlalchemy import func, and_

        base_query = select(ValidationError).where(
            ValidationError.upload_progress_id == upload_id
        )

        if severity:
            base_query = base_query.where(ValidationError.severity == severity)

        # Get total count
        count_query = select(func.count()).select_from(base_query.subquery())
        total_result = await self.db.execute(count_query)
        total_count = total_result.scalar() or 0

        # Get paginated errors
        query = base_query.order_by(ValidationError.created_at).limit(limit).offset(offset)
        result = await self.db.execute(query)
        errors = result.scalars().all()

        logger.info(
            f"Retrieved {len(errors)} errors for upload {upload_id} "
            f"(total: {total_count}, limit: {limit}, offset: {offset})"
        )

        return list(errors), total_count

    async def get_upload_history(
        self,
        limit: int = 50,
        offset: int = 0
    ) -> tuple[List[UploadHistory], int]:
        """
        Get upload history for company.

        Args:
            limit: Maximum number of records to return
            offset: Offset for pagination

        Returns:
            Tuple of (history list, total count)
        """
        from sqlalchemy import func

        # Get total count
        count_query = select(func.count()).select_from(
            select(UploadHistory).where(
                UploadHistory.company_id == self.company_id
            ).subquery()
        )
        total_result = await self.db.execute(count_query)
        total_count = total_result.scalar() or 0

        # Get paginated history
        query = (
            select(UploadHistory)
            .where(UploadHistory.company_id == self.company_id)
            .order_by(UploadHistory.upload_date.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(query)
        history = result.scalars().all()

        logger.info(
            f"Retrieved {len(history)} history records for company {self.company_id} "
            f"(total: {total_count}, limit: {limit}, offset: {offset})"
        )

        return list(history), total_count

    def _save_preview_and_mapping(
        self,
        upload: UploadProgress,
        first_rows: List[Dict[str, Any]],
        last_rows: List[Dict[str, Any]],
        summary: Dict[str, Any],
        source_type: str,
        column_names: List[str]
    ) -> None:
        """Generate and save preview/mapping dictionary metadata to upload.meta_info."""
        from app.services.mapping_service import MappingService
        
        suggested_mapping, confidence = MappingService.suggest_mappings(
            source_columns=column_names,
            source_type=source_type
        )
        
        preview_data = {
            "first_rows": first_rows,
            "last_rows": last_rows
        }
        
        mapping_data = {
            "suggested_mapping": suggested_mapping,
            "confidence_scores": confidence,
            "confirmed_mapping": {}
        }
        
        meta = dict(upload.meta_info) if upload.meta_info else {}
        meta["preview_data"] = preview_data
        meta["summary"] = summary
        meta["mapping_data"] = mapping_data
        
        # Recursively clean any NaN values to avoid database JSONB validation crash
        import math
        import pandas as pd
        
        def clean_nans(val):
            if isinstance(val, dict):
                return {k: clean_nans(v) for k, v in val.items()}
            elif isinstance(val, list):
                return [clean_nans(x) for x in val]
            elif isinstance(val, float):
                if math.isnan(val) or val != val:
                    return None
                return val
            elif pd.isna(val):
                return None
            return val

        meta = clean_nans(meta)
        upload.meta_info = meta
        flag_modified(upload, "meta_info")

    def _update_stage_timestamp(self, upload: UploadProgress, stage: str, timestamp_type: str = "start") -> None:
        """
        Record stage start/end timestamp in upload.meta_info.
        """
        meta = dict(upload.meta_info) if upload.meta_info else {}
        if "stage_timestamps" not in meta:
            meta["stage_timestamps"] = {}
        if stage not in meta["stage_timestamps"]:
            meta["stage_timestamps"][stage] = {}
        meta["stage_timestamps"][stage][timestamp_type] = datetime.now(timezone.utc).isoformat()
        upload.meta_info = meta
        flag_modified(upload, "meta_info")

    async def _is_cancelled(self, upload_id: str) -> bool:
        """Check if the upload has been marked as cancelled."""
        result = await self.db.execute(
            select(UploadProgress.status).where(
                UploadProgress.id == upload_id,
                UploadProgress.company_id == self.company_id
            )
        )
        status = result.scalar_one_or_none()
        return status == UploadStatus.CANCELLED.value

    async def process_upload_file_async(
        self,
        upload_id: str,
        file_path: str,
        validate_immediately: bool = True
    ) -> None:
        """
        Asynchronously process uploaded file in chunks: parse, validate, and track progress.
        Designed for background Celery worker execution.
        """
        import json
        import pandas as pd

        # 1. Fetch upload record
        result = await self.db.execute(
            select(UploadProgress).where(
                UploadProgress.id == upload_id,
                UploadProgress.company_id == self.company_id
            )
        )
        upload = result.scalar_one_or_none()

        if not upload:
            raise ValueError(f"Upload {upload_id} not found")

        try:
            # 2. Update status to PARSING
            upload.status = UploadStatus.PARSING.value
            upload.current_stage = "parse"
            upload.progress_percentage = 20
            upload.updated_at = datetime.now(timezone.utc)
            self._update_stage_timestamp(upload, "uploading", "end")
            self._update_stage_timestamp(upload, "parsing", "start")
            await self.db.flush()
            await self.db.commit()

            # 3. Validate file metadata and format
            logger.info(f"Validating file {file_path} for upload {upload_id} asynchronously")
            file_validation = self.file_parser.validate_file(file_path)
            
            if not file_validation.is_valid:
                raise ValueError(f"File validation failed: {file_validation.error_message}")

            file_type_str = file_validation.file_format.value if file_validation.file_format else upload.file_type
            upload.file_type = file_type_str
            
            # Determine total rows and columns dynamically
            column_names = []
            total_rows = 0
            delimiter = None
            if file_type_str == "csv":
                delimiter = self.file_parser._detect_csv_delimiter(file_path) or ','
                total_rows = self.file_parser._count_csv_rows(file_path, delimiter)
                try:
                    df_head = pd.read_csv(file_path, delimiter=delimiter, nrows=1)
                    column_names = df_head.columns.tolist()
                    del df_head
                except Exception:
                    column_names = []
            elif file_type_str in ["xlsx", "xls"]:
                engine = 'openpyxl' if file_type_str == 'xlsx' else 'xlrd'
                try:
                    df = pd.read_excel(file_path, engine=engine)
                    total_rows = len(df)
                    column_names = df.columns.tolist()
                    del df
                except Exception as e:
                    logger.warning(f"Failed to read Excel for row counting: {str(e)}")
                    total_rows = 0
            elif file_type_str == "json":
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    if isinstance(data, list):
                        total_rows = len(data)
                        if total_rows > 0:
                            column_names = list(data[0].keys())
                    else:
                        for key, val in data.items():
                            if isinstance(val, list):
                                total_rows = len(val)
                                if total_rows > 0:
                                    column_names = list(val[0].keys())
                                break
                    del data
                except Exception as e:
                    logger.warning(f"Failed to read JSON for row counting: {str(e)}")
                    total_rows = 0

            upload.total_rows = total_rows
            upload.updated_at = datetime.now(timezone.utc)
            self._update_stage_timestamp(upload, "parsing", "end")
            self._update_stage_timestamp(upload, "validating", "start")
            await self.db.flush()
            await self.db.commit()

            # Initialize calculator for summary and preview
            from app.services.preview_service import StreamingSummaryCalculator
            summary_calc = StreamingSummaryCalculator(column_names)
            first_rows = []
            last_rows_buffer = []

            # 4. Stream file chunk by chunk and validate
            total_rows_processed = 0
            total_errors = 0
            total_warnings = 0
            total_blocking_errors = 0

            source_type = upload.meta_info.get("source_type", "transaction") if upload.meta_info else "transaction"
            logger.info(f"Streaming file {file_path} of type {file_type_str} for validation")
            
            # Start streaming
            for chunk in self.file_parser.stream_file(file_path, FileType(file_type_str)):
                # Check for cancellation periodically
                if await self._is_cancelled(upload_id):
                    logger.info(f"Upload {upload_id} has been cancelled by user. Aborting.")
                    # Cancellation is user-initiated — drop the staged file
                    # so /tmp/uploads/ doesn't accumulate orphans.
                    await self.remove_staged_file(file_path)
                    return

                # Update stage to validating
                upload.status = UploadStatus.VALIDATING.value
                upload.current_stage = "validate"
                upload.updated_at = datetime.now(timezone.utc)

                # Validate this chunk
                validation_result = await self._validate_data(upload_id, chunk.data, source_type)

                # Process chunk for summary statistics and samples
                summary_calc.process_chunk(chunk.data)
                if chunk.chunk_index == 1:
                    first_rows = chunk.data[:10]
                last_rows_buffer.extend(chunk.data)
                if len(last_rows_buffer) > 5:
                    last_rows_buffer = last_rows_buffer[-5:]

                # Store errors
                for error in validation_result.errors:
                    if error.is_blocking:
                        total_blocking_errors += 1
                    if error.severity.value == "error":
                        total_errors += 1
                    elif error.severity.value == "warning":
                        total_warnings += 1

                    # Cap database validation records to avoid massive database bottleneck
                    if (total_errors + total_warnings) <= 1000:
                        error_type_map = {
                            "validation_error": "validation",
                            "business_rule": "business_rule",
                            "data_quality": "validation",
                            "parsing_error": "parsing",
                            "system_error": "system"
                        }
                        error_type_value = error_type_map.get(error.error_type.value, "validation")

                        validation_error = ValidationError(
                            id=str(uuid.uuid4()),
                            upload_progress_id=upload.id,
                            row_number=error.row_number + chunk.start_row if error.row_number is not None else None,
                            column_name=error.column_name,
                            raw_value=error.raw_value,
                            error_type=error_type_value,
                            error_category=error.error_category.value,
                            error_message=error.error_message,
                            severity=error.severity.value,
                            is_blocking=error.is_blocking,
                            error_metadata=error.meta_info,
                            created_at=error.created_at
                        )
                        self.db.add(validation_error)

                # Update progress
                total_rows_processed += chunk.row_count
                
                progress_fraction = chunk.chunk_index / chunk.total_chunks
                progress_percent = int(20 + progress_fraction * 70)  # parse/validate stage is 20-90%

                upload.processed_rows = total_rows_processed
                upload.error_count = total_errors
                upload.warning_count = total_warnings
                upload.progress_percentage = progress_percent
                upload.updated_at = datetime.now(timezone.utc)

                if chunk.chunk_index % 20 == 0 or chunk.chunk_index == chunk.total_chunks:
                    await self.db.flush()
                    await self.db.commit()

            # Finalize progress
            self._update_stage_timestamp(upload, "validating", "end")

            # Generate and save preview / summary / mapping data
            summary = summary_calc.get_summary(
                file_size=upload.file_size or 0,
                file_type=file_type_str,
                encoding="UTF-8",
                delimiter=delimiter if file_type_str == "csv" else None
            )
            self._save_preview_and_mapping(
                upload=upload,
                first_rows=first_rows,
                last_rows=last_rows_buffer,
                summary=summary,
                source_type=source_type,
                column_names=column_names
            )

            # Set status to completed (if no blocking errors) or failed (if blocking errors)
            if total_blocking_errors == 0:
                upload.status = "awaiting_confirm"
                upload.current_stage = "awaiting_confirm"
                upload.progress_percentage = 90
                # Save staged file path
                meta = dict(upload.meta_info) if upload.meta_info else {}
                meta["staged_file_path"] = file_path
                upload.meta_info = meta
                flag_modified(upload, "meta_info")
            else:
                upload.status = UploadStatus.FAILED.value
                upload.error_message = f"Validation failed with {total_blocking_errors} blocking errors."
                upload.progress_percentage = 100

            upload.completed_at = datetime.now(timezone.utc)
            upload.updated_at = datetime.now(timezone.utc)
            await self.db.flush()

            # Create history record
            await self._create_upload_history(upload)

            # Cleanup temp file ONLY if failed
            if upload.status == UploadStatus.FAILED.value:
                await self.cleanup_temp_files(file_path)

            await self.db.commit()

        except Exception as e:
            logger.error(f"Error processing async upload {upload_id}: {str(e)}")
            # Cleanup temp file
            await self.cleanup_temp_files(file_path)
            
            # Reset DB status to failed
            try:
                result = await self.db.execute(
                    select(UploadProgress).where(UploadProgress.id == upload_id)
                )
                upload_to_fail = result.scalar_one_or_none()
                if upload_to_fail and upload_to_fail.status not in [UploadStatus.COMPLETED.value, UploadStatus.FAILED.value, UploadStatus.CANCELLED.value]:
                    upload_to_fail.status = UploadStatus.FAILED.value
                    upload_to_fail.error_message = str(e)[:2000]
                    upload_to_fail.progress_percentage = 0
                    upload_to_fail.completed_at = datetime.now(timezone.utc)
                    upload_to_fail.updated_at = datetime.now(timezone.utc)
                    await self.db.commit()
            except Exception as db_err:
                logger.error(f"Failed to update failed status in database: {str(db_err)}")
            
            raise

    async def cleanup_temp_files(self, file_path: str) -> None:
        """
        Preserves temporary files for audit compliance.

        Args:
            file_path: Path to temporary file
        """
        try:
            if os.path.exists(file_path):
                logger.info(f"Preserving temporary file for audit logs: {file_path}")
        except Exception as e:
            logger.warning(f"Failed to verify temporary file path {file_path}: {str(e)}")

    async def remove_staged_file(self, file_path: str) -> None:
        """
        Remove a staged upload file from disk. Used by the cancel path.

        Unlike `cleanup_temp_files` (which preserves the file for audit on
        failed/importing uploads), this actually unlinks the file. Caller is
        responsible for not invoking this on uploads we want to keep — i.e.
        only call this when the upload has reached a terminal "cancelled"
        status and the user clearly indicated they don't want the data.

        Args:
            file_path: Path to the staged upload file
        """
        if not file_path:
            return
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Removed staged file after cancellation: {file_path}")
        except Exception as e:
            # Best-effort: don't fail the cancel just because the unlink failed.
            logger.warning(f"Failed to remove staged file {file_path}: {str(e)}")


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename to prevent path traversal attacks.

    Args:
        filename: Original filename

    Returns:
        Sanitized filename
    """
    import re
    import unicodedata

    # Remove directory paths
    filename = os.path.basename(filename)

    # Normalize unicode
    filename = unicodedata.normalize('NFKD', filename)

    # Remove dangerous characters (hyphen at end to avoid range interpretation)
    filename = re.sub(r'[^\w\s.-]', '', filename)

    # Limit length
    filename = filename[:255]

    return filename or "uploaded_file"


def save_upload_file_temporarily(file_content: bytes, filename: str) -> str:
    """
    Save uploaded file to temporary location.

    Args:
        file_content: File content as bytes
        filename: Original filename

    Returns:
        Path to temporary file
    """
    # Create temp directory if it doesn't exist
    temp_dir = os.path.abspath(settings.UPLOAD_STAGING_DIR)
    os.makedirs(temp_dir, exist_ok=True)

    # Sanitize filename
    safe_filename = sanitize_filename(filename)

    # Create temporary file
    temp_path = os.path.join(temp_dir, f"{uuid.uuid4()}_{safe_filename}")

    with open(temp_path, 'wb') as f:
        f.write(file_content)

    logger.info(f"Saved upload to temporary file: {temp_path}")

    return temp_path
