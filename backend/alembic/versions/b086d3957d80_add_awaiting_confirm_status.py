"""add awaiting_confirm status
Revision ID: b086d3957d80
Revises: 0002_upload_tables
Create Date: 2026-07-02 11:52:31.724573
"""
from alembic import op
import sqlalchemy as sa

revision = 'b086d3957d80'
down_revision = '0002_upload_tables'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('valid_upload_status', 'upload_progress', type_='check')
    op.create_check_constraint(
        'valid_upload_status',
        'upload_progress',
        "status IN ('pending', 'uploading', 'parsing', 'validating', 'previewing', 'mapping', 'awaiting_confirm', 'confirmed', 'importing', 'completed', 'failed', 'cancelled')"
    )
    
    op.drop_constraint('valid_history_status', 'upload_history', type_='check')
    op.create_check_constraint(
        'valid_history_status',
        'upload_history',
        "status IN ('awaiting_confirm', 'completed', 'failed', 'cancelled')"
    )


def downgrade():
    op.drop_constraint('valid_upload_status', 'upload_progress', type_='check')
    op.create_check_constraint(
        'valid_upload_status',
        'upload_progress',
        "status IN ('pending', 'uploading', 'parsing', 'validating', 'previewing', 'mapping', 'confirmed', 'importing', 'completed', 'failed', 'cancelled')"
    )
    
    op.drop_constraint('valid_history_status', 'upload_history', type_='check')
    op.create_check_constraint(
        'valid_history_status',
        'upload_history',
        "status IN ('completed', 'failed', 'cancelled')"
    )

