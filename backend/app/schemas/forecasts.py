from pydantic import BaseModel
from typing import Any


class GenerateIn(BaseModel):
    dataset_name: str = "default"
    horizon: int = 28
    aggregation: str = "monthly"   # weekly|monthly|yearly
    mapping: dict[str, str] = {}   # canonical -> user column (final mapping)


class SessionOut(BaseModel):
    session_id: str
    status: str
    generated_by: str | None = None
    # From the session's JSON metadata (notes field):
    dataset_name: str | None = None
    horizon: int | None = None
    aggregation: str | None = None
    model_used: str | None = None
    sku_count: int = 0
    row_count: int = 0
    metrics: dict[str, Any] | None = None
    generated_at: str | None = None
    created_at: str | None = None
    published_at: str | None = None


class GenerateOut(BaseModel):
    session_id: str
    status: str


class StatusOut(BaseModel):
    session_id: str
    status: str


class ForecastRowOut(BaseModel):
    item_id: str | None
    date: str | None
    predictions: float | None
    quantile_0_1: float | None = None
    quantile_0_9: float | None = None
    model_used: str | None = None
