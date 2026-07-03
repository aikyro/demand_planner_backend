"""Pydantic schemas for upload endpoints and responses."""

from datetime import datetime
from typing import Optional, Dict, List, Any, Literal
from pydantic import BaseModel, Field, field_validator
from enum import Enum


class UploadStatus(str, Enum):
    """Status of an upload operation."""
    PENDING = "pending"
    UPLOADING = "uploading"
    PARSING = "parsing"
    VALIDATING = "validating"
    PREVIEWING = "previewing"
    MAPPING = "mapping"
    CONFIRMED = "confirmed"
    IMPORTING = "importing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    AWAITING_CONFIRM = "awaiting_confirm"


class ProcessingStage(str, Enum):
    """Processing stages for upload workflow."""
    UPLOAD = "upload"
    PARSE = "parse"
    VALIDATE = "validate"
    IMPORT = "import"


class FileType(str, Enum):
    """Supported file types for upload."""
    CSV = "csv"
    XLSX = "xlsx"
    XLS = "xls"
    JSON = "json"


class UploadRequest(BaseModel):
    """Request schema for file upload."""
    validate_immediately: bool = Field(
        default=True, description="Whether to validate immediately after upload"
    )
    async_processing: bool = Field(
        default=False, description="Whether to use async processing"
    )
    source_type: Optional[str] = Field(
        default="transaction", description="Type of data source"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="Additional upload metadata"
    )


class FileValidationResult(BaseModel):
    """Result of file validation during upload."""
    is_valid: bool = Field(..., description="Whether file passes validation")
    file_format: Optional[str] = Field(None, description="Detected file format")
    file_size: int = Field(..., description="File size in bytes")
    file_size_mb: float = Field(..., description="File size in MB")
    mime_type: Optional[str] = Field(None, description="Detected MIME type")
    encoding: Optional[str] = Field(None, description="Detected file encoding")
    errors: List[str] = Field(default_factory=list, description="Validation errors")
    warnings: List[str] = Field(default_factory=list, description="Validation warnings")


class UploadResponse(BaseModel):
    """Response schema for successful file upload."""
    upload_id: str = Field(..., description="Unique upload identifier")
    status: UploadStatus = Field(..., description="Current upload status")
    file_name: str = Field(..., description="Uploaded file name")
    file_size: int = Field(..., description="File size in bytes")
    file_type: str = Field(..., description="File type")
    total_rows: Optional[int] = Field(None, description="Total rows in file (after parsing)")
    processed_rows: Optional[int] = Field(None, description="Number of rows processed")
    error_count: int = Field(default=0, description="Number of errors")
    warning_count: int = Field(default=0, description="Number of warnings")
    validation_result: Optional[Dict[str, Any]] = Field(
        None, description="Validation result (if validated immediately)"
    )
    created_at: datetime = Field(..., description="Upload timestamp")
    estimated_completion: Optional[datetime] = Field(
        None, description="Estimated completion time for async uploads"
    )


class UploadStatusResponse(BaseModel):
    """Response schema for upload status query."""
    upload_id: str = Field(..., description="Upload identifier")
    status: UploadStatus = Field(..., description="Current upload status")
    current_stage: Optional[str] = Field(None, description="Current processing stage")
    progress_percentage: int = Field(..., description="Progress percentage (0-100)")
    total_rows: Optional[int] = Field(None, description="Total rows to process")
    processed_rows: Optional[int] = Field(None, description="Number of rows processed")
    error_count: int = Field(..., description="Number of errors")
    warning_count: int = Field(..., description="Number of warnings")
    created_at: datetime = Field(..., description="Upload start time")
    updated_at: Optional[datetime] = Field(None, description="Last update time")
    completed_at: Optional[datetime] = Field(None, description="Completion time")
    estimated_completion: Optional[datetime] = Field(
        None, description="Estimated completion time"
    )
    error_message: Optional[str] = Field(None, description="Error message if failed")


class UploadErrorDetail(BaseModel):
    """Detailed information about a single upload error."""
    row_number: Optional[int] = Field(None, description="Row number where error occurred")
    column: Optional[str] = Field(None, description="Column name where error occurred")
    value: Optional[str] = Field(None, description="Value that caused the error")
    error_type: str = Field(..., description="Type of error")
    severity: str = Field(..., description="Error severity (error/warning/info)")
    message: str = Field(..., description="Error message")
    is_blocking: bool = Field(default=True, description="Whether error blocks import")
    created_at: datetime = Field(..., description="When error was detected")


class UploadErrorsResponse(BaseModel):
    """Response schema for upload errors query."""
    upload_id: str = Field(..., description="Upload identifier")
    total_errors: int = Field(..., description="Total number of errors")
    blocking_errors: int = Field(..., description="Number of blocking errors")
    total_warnings: int = Field(..., description="Total number of warnings")
    errors: List[UploadErrorDetail] = Field(..., description="List of errors")
    limit: int = Field(..., description="Limit applied to results")
    offset: int = Field(..., description="Offset applied to results")
    has_more: bool = Field(..., description="Whether more errors exist")


class UploadHistoryResponse(BaseModel):
    """Response schema for upload history."""
    upload_id: str = Field(..., description="Upload identifier")
    file_name: str = Field(..., description="File name")
    file_type: Optional[str] = Field(None, description="File type")
    file_size: Optional[int] = Field(None, description="File size in bytes")
    upload_date: datetime = Field(..., description="Upload date")
    status: str = Field(..., description="Upload status")
    duration_seconds: Optional[int] = Field(None, description="Duration in seconds")
    row_count: Optional[int] = Field(None, description="Number of rows")
    error_count: int = Field(..., description="Number of errors")
    warning_count: int = Field(..., description="Number of warnings")
    result_summary: Dict[str, Any] = Field(
        default_factory=dict, description="Result summary"
    )


class UploadListResponse(BaseModel):
    """Response schema for upload list."""
    uploads: List[UploadHistoryResponse] = Field(..., description="List of uploads")
    total_count: int = Field(..., description="Total number of uploads")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Number of uploads per page")
    has_more: bool = Field(..., description="Whether more uploads exist")


class UploadProgressUpdate(BaseModel):
    """Schema for updating upload progress."""
    status: Optional[UploadStatus] = Field(None, description="New status")
    current_stage: Optional[str] = Field(None, description="Current processing stage")
    progress_percentage: Optional[int] = Field(None, ge=0, le=100, description="Progress percentage")
    total_rows: Optional[int] = Field(None, description="Total rows")
    processed_rows: Optional[int] = Field(None, description="Processed rows")
    error_count: Optional[int] = Field(None, ge=0, description="Error count")
    warning_count: Optional[int] = Field(None, ge=0, description="Warning count")
    error_message: Optional[str] = Field(None, description="Error message")


class ErrorResponse(BaseModel):
    """Standard error response format."""
    detail: str = Field(..., description="Error message")
    error_code: str = Field(..., description="Machine-readable error code")
    errors: Optional[List[Dict[str, Any]]] = Field(
        None, description="Detailed error information"
    )


class ValidationErrorResponse(ErrorResponse):
    """Error response for validation failures."""
    upload_id: Optional[str] = Field(None, description="Upload identifier")
    status: UploadStatus = Field(..., description="Upload status")
    error_summary: Optional[Dict[str, Any]] = Field(
        None, description="Summary of validation errors"
    )


class FileUploadErrorResponse(BaseModel):
    """Error response for file upload failures."""
    detail: str = Field(..., description="Error message")
    error_code: str = Field(..., description="Machine-readable error code")
    file_name: Optional[str] = Field(None, description="File name that failed")
    file_size: Optional[int] = Field(None, description="File size")
    reason: Optional[str] = Field(None, description="Detailed failure reason")
    allowed_types: List[str] = Field(
        default=["csv", "xlsx", "xls", "json"], description="Allowed file types"
    )
    max_size: int = Field(
        default=50 * 1024 * 1024, description="Maximum allowed file size in bytes"
    )


@field_validator("progress_percentage")
def validate_progress_percentage(cls, v: Optional[int]) -> Optional[int]:
    """Validate progress percentage is between 0 and 100."""
    if v is not None and (v < 0 or v > 100):
        raise ValueError("progress_percentage must be between 0 and 100")
    return v
