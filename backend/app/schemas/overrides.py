from pydantic import BaseModel


class OverrideIn(BaseModel):
    forecast_id: str
    override_value: float
    reason: str | None = None


class OverrideOut(BaseModel):
    id: str
    forecast_id: str
    product_id: str
    original_value: float
    override_value: float
    pct_change: float | None = None
    status: str
    reason: str | None = None
    created_at: str | None = None
    approved_by: str | None = None
    approved_at: str | None = None


class DecisionIn(BaseModel):
    comments: str | None = None
