"""Pydantic schemas for upload history and audit trail."""

from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class HistoryStageInfo(BaseModel):
    """Stage duration and status summary in audit log."""
    duration: Optional[str] = Field(None, description="Formatted duration in HH:MM:SS")
    status: str = Field(..., description="Stage final status (e.g. completed, failed)")


class HistoryUserSummary(BaseModel):
    """User summary details for audit log."""
    id: str = Field(..., description="Unique user identifier")
    name: str = Field(..., description="User full name")


class HistorySourceConfigSummary(BaseModel):
    """Source configuration summary for audit log."""
    id: str = Field(..., description="Unique configuration identifier")
    name: str = Field(..., description="Configuration name")


class UploadHistoryItem(BaseModel):
    """Item schema for listing upload histories."""
    upload_id: str = Field(..., description="Unique upload identifier")
    file_name: str = Field(..., description="Staged filename")
    upload_date: datetime = Field(..., description="When upload was initiated")
    status: str = Field(..., description="Final processing state")
    duration: Optional[str] = Field(None, description="Total execution duration in HH:MM:SS")
    row_count: Optional[int] = Field(None, description="Number of rows imported")
    error_count: int = Field(..., description="Final count of errors")
    warning_count: int = Field(..., description="Final count of warnings")
    file_size: Optional[int] = Field(None, description="File size in bytes")
    file_type: Optional[str] = Field(None, description="File format extension")
    columns: Optional[List[str]] = Field(default=None, description="Column headers of the uploaded dataset")
    source_type: Optional[str] = Field(None, description="Source type of data (e.g. sales, calendar, actuals)")
    session_id: Optional[str] = Field(None, description="Forecast session ID (if applicable, e.g. actuals)")


class UploadHistoryListResponse(BaseModel):
    """Response schema for upload history list query."""
    total_count: int = Field(..., description="Total matching history records")
    uploads: List[UploadHistoryItem] = Field(..., description="List of history details")


class UploadHistoryDetailResponse(BaseModel):
    """Response schema for single upload history details."""
    upload_id: str = Field(..., description="Unique upload identifier")
    file_name: str = Field(..., description="Staged filename")
    upload_date: datetime = Field(..., description="When upload was initiated")
    completed_date: Optional[datetime] = Field(None, description="When upload finished processing")
    duration: Optional[str] = Field(None, description="Total execution duration in HH:MM:SS")
    status: str = Field(..., description="Final processing state")
    row_count: Optional[int] = Field(None, description="Number of rows imported")
    error_count: int = Field(..., description="Final count of errors")
    warning_count: int = Field(..., description="Final count of warnings")
    file_size: Optional[int] = Field(None, description="File size in bytes")
    file_type: Optional[str] = Field(None, description="File format extension")
    user: Optional[HistoryUserSummary] = Field(None, description="User triggering upload")
    source_config: Optional[HistorySourceConfigSummary] = Field(None, description="Associated source config")
    stages: Dict[str, HistoryStageInfo] = Field(..., description="Duration per processing stage")
