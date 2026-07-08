"""rename lookup columns
Revision ID: 0b672e18a250
Revises: a1b2c3d4e5f6
Create Date: 2026-07-07 18:05:52.131156
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = '0b672e18a250'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None

def upgrade():
    # Only apply the lookup column renaming
    op.alter_column('lookup', 'product_id', new_column_name='item_id')
    op.alter_column('lookup', 'product_name', new_column_name='item_name')
    op.alter_column('lookup', 'location_id', new_column_name='store_id')
    op.alter_column('lookup', 'location_name', new_column_name='store_name')

def downgrade():
    op.alter_column('lookup', 'item_id', new_column_name='product_id')
    op.alter_column('lookup', 'item_name', new_column_name='product_name')
    op.alter_column('lookup', 'store_id', new_column_name='location_id')
    op.alter_column('lookup', 'store_name', new_column_name='location_name')
