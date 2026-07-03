"""add upload tracking and validation tables

Revision ID: 0002_upload_tables
Revises: 0001_init
Create Date: 2026-07-01

This migration creates the foundation tables for the enhanced upload system:
- upload_progress: Track async upload processing status
- validation_errors: Store detailed validation errors
- upload_history: Maintain upload audit trail
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0002_upload_tables"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade():
    # Create upload_progress table
    op.create_table(
        "upload_progress",
        sa.Column(
            "id",
            sa.String(50),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()::text")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("company_id", sa.String(50), nullable=False),
        sa.Column("source_config_id", sa.String(50), nullable=True),
        sa.Column("user_id", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("current_stage", sa.String(50), nullable=True),
        sa.Column(
            "progress_percentage",
            sa.Integer(),
            server_default="0",
            nullable=False
        ),
        sa.Column("total_rows", sa.Integer(), nullable=True),
        sa.Column("processed_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("warning_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("file_name", sa.String(255), nullable=True),
        sa.Column("file_type", sa.String(50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("meta_info", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_config_id"], ["source_configs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "status IN ('pending', 'uploading', 'parsing', 'validating', 'previewing', 'mapping', 'confirmed', 'importing', 'completed', 'failed', 'cancelled')",
            name="valid_upload_status"
        ),
        sa.CheckConstraint(
            "progress_percentage >= 0 AND progress_percentage <= 100",
            name="valid_progress_range"
        ),
    )

    # Create validation_errors table
    op.create_table(
        "validation_errors",
        sa.Column(
            "id",
            sa.String(50),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()::text")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("upload_progress_id", sa.String(50), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=True),
        sa.Column("column_name", sa.String(100), nullable=True),
        sa.Column("raw_value", sa.Text(), nullable=True),
        sa.Column("error_type", sa.String(50), nullable=False),
        sa.Column("error_category", sa.String(50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(20), server_default="error", nullable=False),
        sa.Column("is_blocking", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("metadata", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.ForeignKeyConstraint(
            ["upload_progress_id"],
            ["upload_progress.id"],
            ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "error_type IN ('validation', 'parsing', 'database', 'business_rule', 'system')",
            name="valid_error_type"
        ),
        sa.CheckConstraint(
            "severity IN ('error', 'warning', 'info')",
            name="valid_severity"
        ),
    )

    # Create upload_history table
    op.create_table(
        "upload_history",
        sa.Column(
            "id",
            sa.String(50),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()::text")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("company_id", sa.String(50), nullable=False),
        sa.Column("user_id", sa.String(50), nullable=False),
        sa.Column("source_config_id", sa.String(50), nullable=True),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_type", sa.String(50), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("upload_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("error_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("warning_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("result_summary", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_config_id"], ["source_configs.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('completed', 'failed', 'cancelled')",
            name="valid_history_status"
        ),
    )

    # Create indexes for upload_progress
    op.create_index(
        "idx_upload_progress_company_status",
        "upload_progress",
        ["company_id", "status"]
    )
    op.create_index(
        "idx_upload_progress_user_uploads",
        "upload_progress",
        ["user_id", "created_at"]
    )

    # Create indexes for validation_errors
    op.create_index(
        "idx_validation_errors_upload",
        "validation_errors",
        ["upload_progress_id", "severity"]
    )
    op.create_index(
        "idx_validation_errors_type",
        "validation_errors",
        ["error_type", "error_category"]
    )

    # Create indexes for upload_history
    op.create_index(
        "idx_upload_history_company",
        "upload_history",
        ["company_id", "upload_date"]
    )
    op.create_index(
        "idx_upload_history_user",
        "upload_history",
        ["user_id", "upload_date"]
    )
    op.create_index(
        "idx_upload_history_status",
        "upload_history",
        ["status", "upload_date"]
    )


def downgrade():
    # Drop indexes first (in reverse order)
    op.drop_index("idx_upload_history_status", table_name="upload_history")
    op.drop_index("idx_upload_history_user", table_name="upload_history")
    op.drop_index("idx_upload_history_company", table_name="upload_history")

    op.drop_index("idx_validation_errors_type", table_name="validation_errors")
    op.drop_index("idx_validation_errors_upload", table_name="validation_errors")

    op.drop_index("idx_upload_progress_user_uploads", table_name="upload_progress")
    op.drop_index("idx_upload_progress_company_status", table_name="upload_progress")

    # Drop tables (in reverse order)
    op.drop_table("upload_history")
    op.drop_table("validation_errors")
    op.drop_table("upload_progress")
