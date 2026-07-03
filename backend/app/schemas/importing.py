from pydantic import BaseModel
from typing import Any

# Canonical target columns
TXN_COLUMNS = ["product_id", "location_id", "date", "quantity", "revenue", "price"]
LOOKUP_COLUMNS = [
    "product_id", "product_name", "category", "brand",
    "location_id", "location_name", "state", "region", "channel",
]

# M5 Dataset Columns
CALENDAR_COLUMNS = [
    "date", "wm_yr_wk", "weekday", "wday", "month", "year", "d",
    "event_name_1", "event_type_1", "event_name_2", "event_type_2",
    "snap_CA", "snap_TX", "snap_WI"
]
SELL_PRICES_COLUMNS = ["store_id", "item_id", "wm_yr_wk", "sell_price"]
SALES_COLUMNS = ["item_store_id", "item_id", "dept_id", "cat_id", "store_id", "state_id", "d", "sales"]


class SourceConfigIn(BaseModel):
    file_name: str
    file_type: str  # sales|price|inventory|lookup|actuals
    column_mappings: dict[str, str] = {}  # canonical -> user column


class SourceConfigOut(BaseModel):
    id: str
    file_name: str
    file_type: str
    column_mappings: dict[str, str]
    is_active: bool


class MappingIn(BaseModel):
    column_mappings: dict[str, str]


class ImportIn(BaseModel):
    rows: list[dict[str, Any]]            # raw rows as parsed by the frontend
    upload_date: str | None = None


class ImportOut(BaseModel):
    upload_id: str
    row_count: int
    columns: list[str]


class LookupImportIn(BaseModel):
    rows: list[dict[str, Any]]
    column_mappings: dict[str, str]       # canonical -> user column


class LookupImportOut(BaseModel):
    inserted: int
