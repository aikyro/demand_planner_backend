"""Pydantic schemas for upload progress tracking and summary response."""

from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class StageProgressDetail(BaseModel):
    """Progress details for a specific stage."""
    percentage: int = Field(..., description="Progress percentage within this stage (0-100)")
    status: str = Field(..., description="Stage status: pending, in_progress, completed, failed, cancelled")


class UploadProgressResponse(BaseModel):
    """Response schema for upload progress query."""
    upload_id: str = Field(..., description="Unique upload identifier")
    status: str = Field(..., description="Overall upload status")
    current_stage: Optional[str] = Field(None, description="Current stage name")
    stage_progress: Dict[str, StageProgressDetail] = Field(..., description="Progress dictionary for each stage")
    overall_progress: int = Field(..., description="Overall progress percentage (0-100)")
    processed_rows: int = Field(..., description="Number of rows processed so far")
    total_rows: Optional[int] = Field(None, description="Total number of rows to process")
    error_count: int = Field(..., description="Number of errors found")
    warning_count: int = Field(..., description="Number of warnings found")
    estimated_completion: Optional[datetime] = Field(None, description="Estimated completion timestamp")
    started_at: datetime = Field(..., description="When processing started")
    updated_at: Optional[datetime] = Field(None, description="Last progress update time")


class UploadStatusItem(BaseModel):
    """Status summary item for an upload."""
    upload_id: str = Field(..., description="Unique upload identifier")
    status: str = Field(..., description="Upload status")
    current_stage: Optional[str] = Field(None, description="Current stage name")
    overall_progress: int = Field(..., description="Overall progress percentage (0-100)")


class MultipleUploadStatusesResponse(BaseModel):
    """Response schema for querying multiple upload statuses."""
    uploads: List[UploadStatusItem] = Field(..., description="List of upload statuses")


class StageDuration(BaseModel):
    """Duration details for a stage."""
    duration: Optional[str] = Field(None, description="Duration in HH:MM:SS format")


class UploadSummaryResponse(BaseModel):
    """Response schema for upload processing summary."""
    upload_id: str = Field(..., description="Unique upload identifier")
    file_name: Optional[str] = Field(None, description="Uploaded file name")
    file_size: Optional[int] = Field(None, description="File size in bytes")
    file_type: Optional[str] = Field(None, description="File format type")
    upload_date: datetime = Field(..., description="Upload date and time")
    processing_duration: Optional[str] = Field(None, description="Total processing duration in HH:MM:SS")
    status: str = Field(..., description="Final processing status")
    row_count: Optional[int] = Field(None, description="Total number of parsed rows")
    error_count: int = Field(..., description="Final count of errors")
    warning_count: int = Field(..., description="Final count of warnings")
    stages: Dict[str, StageDuration] = Field(..., description="Duration per processing stage")
