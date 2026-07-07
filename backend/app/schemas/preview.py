"""Pydantic schemas for data preview and column mapping."""

from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field


class PreviewData(BaseModel):
    """Container for first and last rows of preview data."""
    first_rows: List[Dict[str, Any]] = Field(..., description="First few rows of the dataset")
    last_rows: List[Dict[str, Any]] = Field(..., description="Last few rows of the dataset")


class PreviewResponse(BaseModel):
    """Response schema for data preview."""
    upload_id: str = Field(..., description="Unique upload identifier")
    preview_data: PreviewData = Field(..., description="Row-based preview of the dataset")
    total_rows: int = Field(..., description="Total rows in the dataset")
    total_columns: int = Field(..., description="Total columns in the dataset")


class DateRange(BaseModel):
    """Date range statistics for a column."""
    start: str = Field(..., description="Earliest date found in ISO format")
    end: str = Field(..., description="Latest date found in ISO format")
    missing_count: int = Field(..., description="Count of invalid or missing dates in this column")


class DatasetSummary(BaseModel):
    """Detailed summary statistics of a dataset."""
    row_count: int = Field(..., description="Total row count")
    column_count: int = Field(..., description="Total column count")
    file_size: int = Field(..., description="Size of file in bytes")
    file_type: str = Field(..., description="File format extension")
    encoding: str = Field(..., description="Detected encoding format")
    delimiter: Optional[str] = Field(None, description="Delimiter (CSV only)")
    estimated_memory_usage: str = Field(..., description="Human-readable memory footprint estimation")
    missing_values: Dict[str, int] = Field(..., description="Missing value counts per column")
    duplicate_rows: int = Field(..., description="Count of identical duplicate rows")
    date_ranges: Dict[str, DateRange] = Field(..., description="Calculated ranges for date-like columns")
    column_types: Dict[str, str] = Field(..., description="Inferred types of each column (string, numeric, date, unknown)")


class DatasetSummaryResponse(BaseModel):
    """Response schema for dataset summary query."""
    upload_id: str = Field(..., description="Unique upload identifier")
    summary: DatasetSummary = Field(..., description="Summary statistics of the dataset")


class MappingSuggestionResponse(BaseModel):
    """Response schema for suggested column mappings."""
    upload_id: str = Field(..., description="Unique upload identifier")
    source_columns: List[str] = Field(..., description="Column headers present in user upload")
    canonical_columns: List[str] = Field(..., description="Canonical columns expected by schema")
    suggested_mapping: Dict[str, str] = Field(..., description="Suggested mappings (user_column -> canonical_column)")
    confidence: Dict[str, float] = Field(..., description="Confidence score for each suggestion (0.0 to 1.0)")
    unmapped_columns: List[str] = Field(..., description="Source columns with no suggested mapping")
    unmapped_canonical: List[str] = Field(..., description="Expected canonical columns with no matches")


class MappingUpdateIn(BaseModel):
    """Request schema for updating column mappings."""
    column_mappings: Dict[str, str] = Field(..., description="Custom mappings (user_column -> canonical_column)")


class MappingValidationResult(BaseModel):
    """Validation checks on mapping updates."""
    is_valid: bool = Field(..., description="Whether mapping meets required field constraints")
    missing_required: List[str] = Field(..., description="Required canonical fields not mapped")
    warnings: List[str] = Field(..., description="Warnings or non-blocking issues")


class MappingUpdateResponse(BaseModel):
    """Response schema for updated mappings."""
    upload_id: str = Field(..., description="Unique upload identifier")
    status: str = Field(..., description="State of the mapping configuration")
    column_mappings: Dict[str, str] = Field(..., description="Updated mappings")
    validation_result: MappingValidationResult = Field(..., description="Validation result of the mapping configuration")


class ConfirmImportIn(BaseModel):
    """Request schema for confirming import."""
    column_mappings: Dict[str, str] = Field(..., description="Confirmed mappings (user_column -> canonical_column)")
    proceed_with_warnings: bool = Field(default=False, description="Proceed even if validation alerts exist")
    source_type: Optional[str] = Field(default=None, description="Dataset category type (e.g. calendar, sell_prices, sales)")
    session_id: Optional[str] = Field(default=None, description="Target forecast session ID for actuals")


class ConfirmImportResponse(BaseModel):
    """Response schema for import confirmation."""
    upload_id: str = Field(..., description="Unique upload identifier")
    status: str = Field(..., description="Status after confirmation (e.g. confirmed)")
    message: str = Field(..., description="Details of final confirmation state")
    estimated_import_time: Optional[str] = Field(None, description="Estimated database import duration in HH:MM:SS")
