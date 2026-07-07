from pydantic import BaseModel


class TrendPoint(BaseModel):
    date: str
    forecast: float
    actual: float | None = None


class RecentSession(BaseModel):
    session_id: str
    status: str
    created_at: str | None = None


class ExecutiveKpisOut(BaseModel):
    total_forecasts: int
    active_items: int
    total_predicted: float
    total_actual: float
    overall_accuracy: float | None  # % (100 - WMAPE); None when no actuals matched
    bias_pct: float | None  # signed % (forecast - actual) / actual
    matched_points: int
    session_count: int
    trend: list[TrendPoint]
    recent_sessions: list[RecentSession]


class DashboardFilterOptions(BaseModel):
    item_ids: list[str]
    sessions: list[RecentSession]


class ShareRow(BaseModel):
    label: str
    volume: float
    share: float


class ParetoStats(BaseModel):
    item_count: int
    top20_count: int
    top20_share: float


class ProductVolume(BaseModel):
    item_id: str
    volume: float


class DistributionOut(BaseModel):
    dim: str
    total_volume: float
    shares: list[ShareRow]
    pareto: ParetoStats
    top_products: list[ProductVolume]
    bottom_products: list[ProductVolume]


class ItemMetric(BaseModel):
    item_id: str | None
    points: int
    forecast_total: float
    actual_total: float
    accuracy: float | None  # % (100 - MAPE)
    mape: float | None
    bias: float | None


class OperationalSummary(BaseModel):
    measured_items: int
    mean_bias: float | None
    std_bias: float | None


class OperationalMetricsOut(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[ItemMetric]
    worst_items: list[ItemMetric]
    summary: OperationalSummary
