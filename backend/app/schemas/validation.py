"""Pydantic schemas for validation results and error reporting."""

from datetime import datetime
from typing import Optional, Dict, List, Any, Literal
from pydantic import BaseModel, Field, field_validator
from enum import Enum


class ErrorType(str, Enum):
    """Types of validation errors."""
    VALIDATION_ERROR = "validation_error"      # Schema violations, missing required fields
    BUSINESS_RULE = "business_rule"             # Business logic violations
    DATA_QUALITY = "data_quality"               # Data quality issues
    PARSING_ERROR = "parsing_error"             # Parse failures
    SYSTEM_ERROR = "system_error"               # System-level issues


class ErrorCategory(str, Enum):
    """Categories of validation errors for grouping and filtering."""
    INVALID_TYPE = "invalid_type"               # Wrong data type for column
    MISSING_REQUIRED = "missing_required"       # Required field is missing
    INVALID_FORMAT = "invalid_format"           # Format doesn't match expected pattern
    OUT_OF_RANGE = "out_of_range"               # Value outside valid range
    REFERENCE_NOT_FOUND = "reference_not_found" # Foreign key reference missing
    DUPLICATE = "duplicate"                      # Duplicate data detected
    INCONSISTENT = "inconsistent"               # Data inconsistency detected
    OUTLIER = "outlier"                          # Statistical outlier detected
    CALCULATION = "calculation"                 # Calculation mismatch detected
    CONSTRAINT = "constraint"                   # Business constraint violated


class Severity(str, Enum):
    """Severity levels for validation errors."""
    ERROR = "error"      # Blocking error that prevents import
    WARNING = "warning"  # Non-blocking issue that should be reviewed
    INFO = "info"        # Informational message for awareness


class ValidationStage(str, Enum):
    """Stages of the validation pipeline."""
    FILE_LEVEL = "file_level"         # File structure validation
    SCHEMA = "schema"                 # Schema compliance validation
    BUSINESS_RULES = "business_rules" # Business rules validation
    DATA_QUALITY = "data_quality"     # Data quality checks
    COMPLETED = "completed"           # Validation complete
    FAILED = "failed"                 # Validation failed


class ValidationErrorDetail(BaseModel):
    """Detailed information about a single validation error."""

    # Location information
    row_number: Optional[int] = Field(None, description="Row number where error occurred (0-indexed)")
    column_name: Optional[str] = Field(None, description="Column name where error occurred")
    raw_value: Optional[str] = Field(None, description="Raw value that caused the error")

    # Error classification
    error_type: ErrorType = Field(..., description="Type of error")
    error_category: ErrorCategory = Field(..., description="Category of error")
    severity: Severity = Field(..., description="Severity level")
    is_blocking: bool = Field(True, description="Whether error blocks import")

    # Error message and context
    error_message: str = Field(..., description="Human-readable error message")
    suggestion: Optional[str] = Field(None, description="Suggested correction or action")
    context: Optional[str] = Field(None, description="Additional context about the error")

    # Metadata
    meta_info: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    created_at: datetime = Field(
        default_factory=datetime.now, description="When error was detected"
    )

    @field_validator("error_message")
    @classmethod
    def validate_message_length(cls, v: str) -> str:
        """Ensure error message is not too long for database storage."""
        if len(v) > 2000:
            return v[:2000] + "..."
        return v


class ValidationStatistics(BaseModel):
    """Summary statistics for validation results."""

    # Row counts
    total_rows: int = Field(0, description="Total rows processed")
    valid_rows: int = Field(0, description="Rows without errors")
    error_rows: int = Field(0, description="Rows with at least one error")
    warning_rows: int = Field(0, description="Rows with only warnings")

    # Error and warning counts
    total_errors: int = Field(0, description="Total number of errors")
    total_warnings: int = Field(0, description="Total number of warnings")
    blocking_errors: int = Field(0, description="Number of blocking errors")

    # Error breakdown by type
    errors_by_type: Dict[ErrorType, int] = Field(
        default_factory=dict, description="Count of errors by type"
    )

    # Error breakdown by category
    errors_by_category: Dict[ErrorCategory, int] = Field(
        default_factory=dict, description="Count of errors by category"
    )

    # Data quality metrics
    missing_values: Dict[str, int] = Field(
        default_factory=dict, description="Count of missing values by column"
    )
    duplicate_count: int = Field(0, description="Number of duplicate rows detected")
    outlier_count: int = Field(0, description="Number of outliers detected")

    # Performance metrics
    duration_seconds: Optional[float] = Field(None, description="Validation duration in seconds")
    rows_per_second: Optional[float] = Field(
        None, description="Processing rate in rows per second"
    )


class ValidationResult(BaseModel):
    """Complete validation result for a dataset."""

    # Overall status
    is_valid: bool = Field(..., description="Whether data passes validation for import")
    can_import: bool = Field(..., description="Whether data can be imported despite warnings")

    # Current stage and progress
    current_stage: ValidationStage = Field(
        ..., description="Current validation stage"
    )
    stage_percentage: float = Field(0.0, description="Progress within current stage (0-100)")

    # Statistics
    statistics: ValidationStatistics = Field(
        default_factory=ValidationStatistics, description="Validation statistics"
    )

    # Error details
    errors: List[ValidationErrorDetail] = Field(
        default_factory=list, description="List of validation errors"
    )

    # Metadata
    file_name: Optional[str] = Field(None, description="File being validated")
    source_type: Optional[str] = Field(None, description="Type of data source")
    validation_rules: Optional[List[str]] = Field(
        None, description="Validation rules applied"
    )

    # Timestamps
    started_at: datetime = Field(
        default_factory=datetime.now, description="When validation started"
    )
    completed_at: Optional[datetime] = Field(None, description="When validation completed")
    duration_seconds: Optional[float] = Field(
        None, description="Total validation duration in seconds"
    )

    @field_validator("stage_percentage", "duration_seconds")
    @classmethod
    def validate_non_negative(cls, v: Optional[float]) -> Optional[float]:
        """Ensure numeric fields are non-negative."""
        if v is not None and v < 0:
            return 0.0
        return v


class ValidationPreview(BaseModel):
    """Preview of validation results for UI display."""

    # Status summary
    is_valid: bool = Field(..., description="Overall validation status")
    can_import: bool = Field(..., description="Whether import is allowed")

    # Quick statistics
    total_rows: int = Field(..., description="Total rows processed")
    valid_percentage: float = Field(..., description="Percentage of valid rows")
    error_count: int = Field(..., description="Total number of errors")
    warning_count: int = Field(..., description="Total number of warnings")

    # Sample errors (first N for display)
    sample_errors: List[ValidationErrorDetail] = Field(
        default_factory=list, description="Sample of errors for display"
    )
    sample_size: int = Field(default=100, description="Number of sample errors to include")

    # Error breakdown
    error_summary: Dict[str, int] = Field(
        default_factory=dict, description="Summary of errors by type/category"
    )

    # Data quality summary
    quality_issues: Dict[str, int] = Field(
        default_factory=dict, description="Summary of data quality issues"
    )

    # Metadata
    validation_completed: bool = Field(False, description="Whether validation is complete")
    estimated_completion: Optional[datetime] = Field(
        None, description="Estimated completion time"
    )


class ValidationReport(BaseModel):
    """Detailed validation report for download or detailed review."""

    # Report metadata
    report_id: str = Field(..., description="Unique report identifier")
    file_name: str = Field(..., description="File that was validated")
    generated_at: datetime = Field(default_factory=datetime.now, description="Report generation time")

    # Validation summary
    validation_result: ValidationResult = Field(..., description="Full validation result")

    # Detailed error listing
    all_errors: List[ValidationErrorDetail] = Field(
        default_factory=list, description="All validation errors"
    )

    # Statistics and metrics
    statistics: ValidationStatistics = Field(..., description="Validation statistics")

    # Recommendations
    recommendations: List[str] = Field(
        default_factory=list, description="Recommendations for fixing issues"
    )

    # Additional context
    validation_context: Dict[str, Any] = Field(
        default_factory=dict, description="Additional validation context"
    )


class ValidationConfig(BaseModel):
    """Configuration for validation behavior."""

    # Validation thresholds
    max_errors_to_display: int = Field(1000, description="Maximum errors to display in UI")
    warning_threshold: int = Field(100, description="Show warning if error count exceeds this")

    # Validation rules to apply
    enable_schema_validation: bool = Field(True, description="Enable schema validation")
    enable_business_rules: bool = Field(True, description="Enable business rules validation")
    enable_data_quality: bool = Field(True, description="Enable data quality checks")

    # Data quality thresholds
    duplicate_threshold: int = Field(1, description="Number of duplicates to allow before error")
    outlier_std_dev: float = Field(3.0, description="Standard deviations for outlier detection")
    missing_value_threshold: float = Field(
        0.5, description="Allow up to this proportion of missing values (0-1)"
    )

    # Business rule parameters
    revenue_tolerance: float = Field(
        0.01, description="Allowed tolerance for revenue calculation (1% by default)"
    )
    allow_future_dates: bool = Field(
        False, description="Whether to allow future dates in historical data"
    )
    min_quantity: float = Field(0, description="Minimum allowed quantity")
    max_quantity: Optional[float] = Field(None, description="Maximum allowed quantity")
    min_price: float = Field(0, description="Minimum allowed price")
    max_price: Optional[float] = Field(None, description="Maximum allowed price")

    # Processing options
    batch_size: int = Field(10000, description="Rows per batch for processing")
    stop_on_first_error: bool = Field(False, description="Stop validation on first error")
    parallel_processing: bool = Field(True, description="Enable parallel processing for large datasets")


class BatchValidationResult(BaseModel):
    """Result of batch validation for a single chunk."""

    batch_id: int = Field(..., description="Batch identifier")
    start_row: int = Field(..., description="Starting row number")
    end_row: int = Field(..., description="Ending row number")
    row_count: int = Field(..., description="Number of rows in batch")

    # Validation results for this batch
    errors: List[ValidationErrorDetail] = Field(
        default_factory=list, description="Errors in this batch"
    )
    valid_count: int = Field(0, description="Number of valid rows in batch")
    error_count: int = Field(0, description="Number of error rows in batch")

    # Performance
    duration_seconds: Optional[float] = Field(None, description="Time to validate this batch")
    rows_per_second: Optional[float] = Field(None, description="Processing rate")

    # Timestamps
    processed_at: datetime = Field(
        default_factory=datetime.now, description="When batch was processed"
    )
