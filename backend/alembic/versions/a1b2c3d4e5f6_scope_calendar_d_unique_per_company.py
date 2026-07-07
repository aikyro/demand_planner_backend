"""scope calendar.d unique to per company

Revision ID: a1b2c3d4e5f6
Revises: b135ed17a7e2
Create Date: 2026-07-06 18:30:00.000000

Background:
    Calendar.d is a calendar-day string like "d_1549". The M5 retail calendar
    uses the same d-values across every tenant, so a global UNIQUE on d
    prevented a second tenant from importing the calendar (UniqueViolationError
    on calendar_d_key).

    Switch to a composite UNIQUE (company_id, d) so per-company replace-in-place
    (DELETE WHERE company_id = ...) works and tenants don't collide on d.
"""
from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6'
down_revision = 'b135ed17a7e2'
branch_labels = None
depends_on = None


def upgrade():
    # Drop the global unique index/constraint on calendar.d if it exists.
    # The constraint name created by SQLAlchemy from `unique=True` on a column
    # is `<tablename>_<colname>_key` — i.e. `calendar_d_key`.
    op.drop_constraint('calendar_d_key', 'calendar', type_='unique')

    # Add a composite UNIQUE scoped per company.
    op.create_unique_constraint(
        'uq_calendar_company_d',
        'calendar',
        ['company_id', 'd'],
    )


def downgrade():
    op.drop_constraint('uq_calendar_company_d', 'calendar', type_='unique')
    op.create_unique_constraint('calendar_d_key', 'calendar', ['d'])