"""Pydantic schemas for file parsing and metadata extraction."""

from datetime import datetime
from typing import Optional, Dict, List, Any, Literal
from pydantic import BaseModel, Field, field_validator
from enum import Enum


class FileType(str, Enum):
    """Supported file types for parsing."""
    CSV = "csv"
    XLSX = "xlsx"
    XLS = "xls"
    JSON = "json"


class ParsingStage(str, Enum):
    """Stages of the file parsing process."""
    DETECTING = "detecting"
    READING = "reading"
    PARSING = "parsing"
    EXTRACTING = "extracting"
    COMPLETED = "completed"
    FAILED = "failed"


class DataType(str, Enum):
    """Data types for column detection."""
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    UNKNOWN = "unknown"


class FileMetadata(BaseModel):
    """Comprehensive metadata extracted from a file."""
    # Basic file information
    file_name: str = Field(..., description="Original file name")
    file_type: FileType = Field(..., description="Detected file type")
    file_size_bytes: int = Field(..., description="File size in bytes")
    file_size_mb: float = Field(..., description="File size in megabytes")

    # Encoding information
    encoding: Optional[str] = Field(None, description="Detected file encoding")
    mime_type: Optional[str] = Field(None, description="Detected MIME type")

    # Data structure information
    total_rows: Optional[int] = Field(None, description="Total number of rows")
    total_columns: Optional[int] = Field(None, description="Total number of columns")
    column_names: Optional[List[str]] = Field(None, description="List of column names")

    # Column metadata
    column_types: Optional[Dict[str, DataType]] = Field(
        None, description="Data types for each column"
    )
    date_columns: Optional[List[str]] = Field(
        None, description="List of columns identified as dates"
    )

    # Format-specific metadata
    csv_delimiter: Optional[str] = Field(None, description="CSV delimiter character")
    csv_quote_char: Optional[str] = Field(None, description="CSV quote character")
    excel_sheet_name: Optional[str] = Field(None, description="Excel sheet name")
    json_structure: Optional[str] = Field(None, description="JSON structure type")

    # Memory and processing information
    estimated_memory_mb: Optional[float] = Field(
        None, description="Estimated memory usage in MB"
    )
    processing_time_seconds: Optional[float] = Field(
        None, description="Time taken to parse the file"
    )

    # Validation flags
    has_header: Optional[bool] = Field(None, description="Whether file has header row")
    is_empty: bool = Field(False, description="Whether file is empty")
    is_corrupted: bool = Field(False, description="Whether file is corrupted")

    # Timestamps
    created_at: datetime = Field(
        default_factory=datetime.now, description="When this metadata was created"
    )

    @field_validator("file_size_mb")
    @classmethod
    def calculate_mb(cls, v: float, info) -> float:
        """Calculate file size in MB from bytes if needed."""
        if "file_size_bytes" in info.data and v == 0:
            return round(info.data["file_size_bytes"] / (1024 * 1024), 2)
        return v


class ColumnMapping(BaseModel):
    """Mapping between source column and target column."""
    source_column: str = Field(..., description="Column name in source file")
    target_column: str = Field(..., description="Column name in target system")
    data_type: DataType = Field(..., description="Data type of the column")
    is_required: bool = Field(default=True, description="Whether column is required")
    transform_function: Optional[str] = Field(
        None, description="Optional transform function to apply"
    )


class ParseResult(BaseModel):
    """Result of parsing a file."""
    # Status information
    success: bool = Field(..., description="Whether parsing was successful")
    stage: ParsingStage = Field(..., description="Current parsing stage")
    message: Optional[str] = Field(None, description="Status message or error description")

    # File information
    file_name: str = Field(..., description="File name that was parsed")
    file_type: FileType = Field(..., description="Type of file that was parsed")

    # Metadata
    metadata: FileMetadata = Field(..., description="Comprehensive file metadata")

    # Sample data (first N rows for preview)
    sample_data: Optional[List[Dict[str, Any]]] = Field(
        None, description="Sample data rows for preview"
    )
    sample_size: int = Field(
        default=10, description="Number of rows included in sample_data"
    )

    # Column mappings (optional, for later phases)
    column_mappings: Optional[List[ColumnMapping]] = Field(
        None, description="Suggested column mappings"
    )

    # Progress tracking (for streaming)
    total_chunks: Optional[int] = Field(None, description="Total chunks for streaming")
    processed_chunks: Optional[int] = Field(
        None, description="Number of chunks processed"
    )
    progress_percentage: Optional[float] = Field(
        None, description="Processing progress (0-100)"
    )

    # Error information
    error_count: int = Field(default=0, description="Total number of errors encountered")
    errors: List[str] = Field(default_factory=list, description="List of error messages")
    warnings: List[str] = Field(
        default_factory=list, description="List of warning messages"
    )

    # Timing information
    started_at: datetime = Field(
        default_factory=datetime.now, description="When parsing started"
    )
    completed_at: Optional[datetime] = Field(
        None, description="When parsing completed"
    )
    duration_seconds: Optional[float] = Field(
        None, description="Total parsing duration in seconds"
    )

    @field_validator("duration_seconds")
    @classmethod
    def calculate_duration(cls, v: Optional[float], info) -> Optional[float]:
        """Calculate duration from timestamps if not provided."""
        if v is None and "completed_at" in info.data and "started_at" in info.data:
            started = info.data["started_at"]
            completed = info.data["completed_at"]
            if completed and started:
                delta = completed - started
                return round(delta.total_seconds(), 2)
        return v


class FileValidationResult(BaseModel):
    """Result of file validation before parsing."""
    is_valid: bool = Field(..., description="Whether file passed validation")
    file_format: Optional[FileType] = Field(None, description="Detected file format")
    confidence: float = Field(..., description="Confidence score of format detection (0-1)")

    # Size validation
    file_size_bytes: int = Field(..., description="File size in bytes")
    file_size_mb: float = Field(..., description="File size in megabytes")
    size_ok: bool = Field(..., description="Whether file size is within limits")

    # Format validation
    format_detected_ok: bool = Field(..., description="Whether format was detected successfully")
    format_matches_extension: bool = Field(
        ..., description="Whether format matches file extension"
    )

    # Integrity validation
    is_corrupted: bool = Field(default=False, description="Whether file is corrupted")
    is_empty: bool = Field(default=False, description="Whether file is empty")
    is_readable: bool = Field(default=True, description="Whether file is readable")

    # MIME type validation
    mime_type_ok: bool = Field(default=True, description="Whether MIME type is valid")
    detected_mime_type: Optional[str] = Field(None, description="Detected MIME type")

    # Encoding information
    encoding: Optional[str] = Field(None, description="Detected file encoding")
    encoding_ok: bool = Field(default=True, description="Whether encoding is supported")

    # Error messages
    error_message: Optional[str] = Field(None, description="Primary error message if validation failed")
    warning_messages: List[str] = Field(
        default_factory=list, description="List of warning messages"
    )

    @field_validator("file_size_mb")
    @classmethod
    def calculate_mb(cls, v: float, info) -> float:
        """Calculate file size in MB from bytes."""
        if "file_size_bytes" in info.data:
            return round(info.data["file_size_bytes"] / (1024 * 1024), 2)
        return v


class StreamingChunk(BaseModel):
    """A chunk of data from streaming file processing."""
    chunk_index: int = Field(..., description="Index of this chunk")
    total_chunks: int = Field(..., description="Total number of chunks")
    data: List[Dict[str, Any]] = Field(..., description="Data rows in this chunk")
    row_count: int = Field(..., description="Number of rows in this chunk")

    # Chunk metadata
    start_row: int = Field(..., description="Starting row number (0-indexed)")
    end_row: int = Field(..., description="Ending row number (inclusive)")

    # Processing information
    processed_at: datetime = Field(
        default_factory=datetime.now, description="When this chunk was processed"
    )
    processing_time_seconds: Optional[float] = Field(
        None, description="Time to process this chunk"
    )


class ParsingProgress(BaseModel):
    """Progress tracking for file parsing operations."""
    # Identifiers
    upload_id: str = Field(..., description="Upload progress ID")

    # Stage tracking
    current_stage: ParsingStage = Field(..., description="Current parsing stage")
    stage_percentage: float = Field(..., description="Progress within current stage (0-100)")

    # Overall progress
    overall_percentage: float = Field(..., description="Overall progress (0-100)")
    message: Optional[str] = Field(None, description="Current status message")

    # Data tracking
    total_rows: Optional[int] = Field(None, description="Total rows to process")
    processed_rows: int = Field(default=0, description="Number of rows processed")

    # Performance tracking
    rows_per_second: Optional[float] = Field(
        None, description="Processing rate in rows/second"
    )
    estimated_remaining_seconds: Optional[int] = Field(
        None, description="Estimated time remaining in seconds"
    )

    # Error tracking
    error_count: int = Field(default=0, description="Number of errors encountered")
    warning_count: int = Field(default=0, description="Number of warnings encountered")

    # Timestamps
    updated_at: datetime = Field(
        default_factory=datetime.now, description="Last update time"
    )
    started_at: datetime = Field(..., description="When parsing started")
    estimated_completion_at: Optional[datetime] = Field(
        None, description="Estimated completion time"
    )

    @field_validator("overall_percentage", "stage_percentage")
    @classmethod
    def validate_percentage(cls, v: float) -> float:
        """Validate percentage is between 0 and 100."""
        return max(0.0, min(100.0, v))


class ParserError(BaseModel):
    """Detailed error information from parsing."""
    error_type: str = Field(..., description="Type of error (e.g., 'format_error', 'encoding_error')")
    error_category: str = Field(
        ..., description="Category of error (e.g., 'file', 'content', 'system')"
    )
    severity: Literal["error", "warning", "info"] = Field(
        ..., description="Severity level of the error"
    )
    message: str = Field(..., description="Human-readable error message")

    # Location information
    row_number: Optional[int] = Field(None, description="Row number where error occurred")
    column_name: Optional[str] = Field(None, description="Column name where error occurred")
    column_index: Optional[int] = Field(None, description="Column index where error occurred")

    # Context information
    raw_value: Optional[str] = Field(None, description="Raw value that caused the error")
    context: Optional[str] = Field(None, description="Additional context about the error")

    # Metadata
    file_position: Optional[int] = Field(None, description="Byte position in file")
    is_blocking: bool = Field(default=True, description="Whether error blocks processing")
    created_at: datetime = Field(
        default_factory=datetime.now, description="When error was created"
    )
