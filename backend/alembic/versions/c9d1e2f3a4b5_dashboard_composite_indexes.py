"""dashboard composite indexes

The live database was found holding only primary-key indexes on the hot
dashboard tables (forecasts, actuals, sales, modeling_data, overrides) —
even the single-column indexes declared on the ORM models were never created
(tables were created outside alembic by the ADK service). Every dashboard
query was a sequential scan (modeling_data ≈ 2M rows, sales ≈ 400k).

Composite indexes match the dashboard access paths:
- forecasts/actuals: joined and filtered on (company_id, session_id, item_id, date)
- sales: segmentation/ABC group-by (company_id, item_id) and dimension filters
- modeling_data: distribution queries filter (company_id, session_id)
- overrides: product-detail history lookup (company_id, forecast_id)

Revision ID: c9d1e2f3a4b5
Revises: 0b672e18a250
Create Date: 2026-07-09
"""
from alembic import op

revision = 'c9d1e2f3a4b5'
down_revision = '0b672e18a250'
branch_labels = None
depends_on = None

INDEXES = [
    ("ix_forecasts_company_session_item_date", "forecasts",
     ["company_id", "session_id", "item_id", "date"]),
    ("ix_actuals_company_session_item_date", "actuals",
     ["company_id", "session_id", "item_id", "date"]),
    ("ix_sales_company_cat_store_state", "sales",
     ["company_id", "cat_id", "store_id", "state_id"]),
    ("ix_sales_company_item", "sales", ["company_id", "item_id"]),
    ("ix_modeling_data_company_session", "modeling_data",
     ["company_id", "session_id"]),
    ("ix_overrides_company_forecast", "overrides",
     ["company_id", "forecast_id"]),
]


def upgrade():
    for name, table, cols in INDEXES:
        # if_not_exists guards against duplicates in environments where some
        # index already exists (per handover rule: no duplicate indexes).
        op.create_index(name, table, cols, if_not_exists=True)


def downgrade():
    for name, table, _cols in reversed(INDEXES):
        op.drop_index(name, table_name=table, if_exists=True)
