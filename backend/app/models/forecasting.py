import uuid
from datetime import datetime
from sqlalchemy import String, ForeignKey, Numeric, Date, DateTime, Integer, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, UUIDMixin, TimestampMixin


class ForecastSession(Base, TimestampMixin):
    __tablename__ = "forecast_sessions"
    session_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    generated_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ModelingData(Base, TimestampMixin):
    """
    Preprocessed input data for forecasting models.

    This table has a FIXED schema with the following columns:
    - id, session_id, company_id, created_at (metadata)
    - date, wm_yr_wk, weekday, wday, month, year, d (date dimensions)
    - event_name_1, event_type_1, event_name_2, event_type_2 (events)
    - snap_ca, snap_tx, snap_wi (snap events)
    - item_id, dept_id, cat_id, store_id, state_id (product/location)
    - sell_price, sales, is_active, item_store_id (sales data)

    All data stored as actual relational columns (NOT JSONB).
    Created by ADK execution_tracker.py save_quality_scorer_extra().
    """
    __tablename__ = "modeling_data"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(255), index=True)
    company_id: Mapped[str] = mapped_column(String(50), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Forecast(Base, TimestampMixin):
    """
    Forecast predictions with prediction intervals.

    This table has a FIXED schema with the following columns:
    - id, session_id, company_id, model_used, created_at (metadata)
    - date, target_name (forecast date and item identifier)
    - predictions (main forecast value)
    - quantile_0_1, quantile_0_5, quantile_0_9 (prediction intervals)
    - item_id (to be added via migration)

    All data stored as actual relational columns (NOT JSONB).
    Created by ADK execution_tracker.py save_forecast_extra().
    """
    __tablename__ = "forecasts"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(255), index=True)
    company_id: Mapped[str] = mapped_column(String(50), index=True)
    model_used: Mapped[str | None] = mapped_column(String(50), nullable=True)
    date: Mapped[datetime.date] = mapped_column(Date(), nullable=True)
    target_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    predictions: Mapped[float | None] = mapped_column(Numeric(15, 4), nullable=True)
    quantile_0_1: Mapped[float | None] = mapped_column(Numeric(15, 4), nullable=True)
    quantile_0_5: Mapped[float | None] = mapped_column(Numeric(15, 4), nullable=True)
    quantile_0_9: Mapped[float | None] = mapped_column(Numeric(15, 4), nullable=True)
    item_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Actual(Base, TimestampMixin):
    """
    Actual values for accuracy calculations against forecasts.

    Links to forecasts via session_id + company_id + item_id.
    Used for calculating accuracy, bias, MAPE and other performance metrics.

    All data stored as actual relational columns.
    """
    __tablename__ = "actuals"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    company_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    item_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date(), nullable=False)
    actual_value: Mapped[float] = mapped_column(Numeric(15, 4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentTrace(Base, UUIDMixin):
    __tablename__ = "agent_traces"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    agent_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    input_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="complete")
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
