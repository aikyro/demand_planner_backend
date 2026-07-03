"""Upload tracking and validation models for enhanced data upload system."""

from sqlalchemy import String, Integer, BigInteger, Boolean, Text, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, UUIDMixin, TimestampMixin


class UploadProgress(Base, UUIDMixin, TimestampMixin):
    """Track async upload processing status and progress."""

    __tablename__ = "upload_progress"

    # Foreign keys
    company_id: Mapped[str] = mapped_column(String(50), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    source_config_id: Mapped[str | None] = mapped_column(String(50), ForeignKey("source_configs.id", ondelete="SET NULL"), nullable=True)
    user_id: Mapped[str] = mapped_column(String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Status tracking
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    current_stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    progress_percentage: Mapped[int] = mapped_column(Integer, default=0)

    # Row tracking
    total_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processed_rows: Mapped[int] = mapped_column(Integer, default=0)

    # Error and warning counts
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)

    # File information
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Error message and metadata
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_info: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Timestamps
    updated_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    source_config: Mapped["SourceConfig"] = relationship(
        "SourceConfig", back_populates="upload_progress"
    )
    validation_errors: Mapped[list["ValidationError"]] = relationship(
        "ValidationError", back_populates="upload_progress", cascade="all, delete-orphan"
    )


class ValidationError(Base, UUIDMixin):
    """Store detailed validation errors for upload troubleshooting."""

    __tablename__ = "validation_errors"

    # Foreign key
    upload_progress_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("upload_progress.id", ondelete="CASCADE"),
        nullable=False
    )

    # Error location and context
    row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    column_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    raw_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Error classification
    error_type: Mapped[str] = mapped_column(String(50), nullable=False)
    error_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="error")

    # Error impact
    is_blocking: Mapped[bool] = mapped_column(Boolean, default=True)

    # Additional metadata (column name is 'metadata' in database, Python attr is error_metadata)
    error_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    upload_progress: Mapped["UploadProgress"] = relationship(
        "UploadProgress", back_populates="validation_errors"
    )


class UploadHistory(Base, UUIDMixin):
    """Maintain upload audit trail for compliance and analytics."""

    __tablename__ = "upload_history"

    # Foreign keys
    company_id: Mapped[str] = mapped_column(String(50), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_config_id: Mapped[str | None] = mapped_column(String(50), ForeignKey("source_configs.id", ondelete="SET NULL"), nullable=True)

    # File information
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Upload metadata
    upload_date: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)

    # Statistics
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)

    # Result summary
    result_summary: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Relationships
    source_config: Mapped["SourceConfig"] = relationship(
        "SourceConfig", back_populates="upload_history"
    )
