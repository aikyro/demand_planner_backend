import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, Integer, Numeric, Date, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, UUIDMixin, TimestampMixin
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # These are only imported for type checking, not at runtime
    from app.models.upload import UploadProgress, UploadHistory



class SourceConfig(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "source_configs"
    company_id: Mapped[str] = mapped_column(String(50))
    file_name: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(50))
    column_mappings: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships to upload tracking
    upload_progress: Mapped[list["UploadProgress"]] = relationship(
        "UploadProgress", back_populates="source_config", cascade="all, delete-orphan"
    )
    upload_history: Mapped[list["UploadHistory"]] = relationship(
        "UploadHistory", back_populates="source_config", cascade="all, delete-orphan"
    )


class DataUpload(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "data_uploads"
    company_id: Mapped[str] = mapped_column(String(50))
    source_config_id: Mapped[str] = mapped_column(String(50))
    upload_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    row_count: Mapped[int] = mapped_column(default=0)
    data: Mapped[list] = mapped_column(JSONB, default=list)


class Lookup(Base, UUIDMixin):
    __tablename__ = "lookup"
    company_id: Mapped[str] = mapped_column(String(50))
    product_id: Mapped[str] = mapped_column(String(120))
    product_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(120), nullable=True)
    location_id: Mapped[str] = mapped_column(String(120))
    location_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    region: Mapped[str | None] = mapped_column(String(120), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Calendar(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "calendar"
    __table_args__ = (
        UniqueConstraint("company_id", "d", name="uq_calendar_company_d"),
    )
    company_id: Mapped[str] = mapped_column(String(50), index=True)
    date: Mapped[datetime] = mapped_column(Date, nullable=False)
    wm_yr_wk: Mapped[int] = mapped_column(Integer, nullable=False)
    weekday: Mapped[str] = mapped_column(String(20))
    wday: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    year: Mapped[int] = mapped_column(Integer)
    # NOTE: `d` is a calendar-day string like "d_1549". The M5 retail calendar
    # uses the same `d` values across every tenant, so a global UNIQUE here
    # would block a second tenant from ever importing the calendar. Scope
    # uniqueness to (company_id, d) instead — see uq_calendar_company_d above.
    d: Mapped[str] = mapped_column(String(10))
    event_name_1: Mapped[str | None] = mapped_column(String(100), nullable=True)
    event_type_1: Mapped[str | None] = mapped_column(String(50), nullable=True)
    event_name_2: Mapped[str | None] = mapped_column(String(100), nullable=True)
    event_type_2: Mapped[str | None] = mapped_column(String(50), nullable=True)
    snap_CA: Mapped[int] = mapped_column(Integer, default=0)
    snap_TX: Mapped[int] = mapped_column(Integer, default=0)
    snap_WI: Mapped[int] = mapped_column(Integer, default=0)


class SellPrice(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "sell_prices"
    company_id: Mapped[str] = mapped_column(String(50), index=True)
    store_id: Mapped[str] = mapped_column(String(50))
    item_id: Mapped[str] = mapped_column(String(100))
    wm_yr_wk: Mapped[int] = mapped_column(Integer)
    sell_price: Mapped[float] = mapped_column(Numeric(10, 4))


class Sales(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "sales"
    company_id: Mapped[str] = mapped_column(String(50), index=True)
    item_id: Mapped[str] = mapped_column(String(100))
    dept_id: Mapped[str] = mapped_column(String(50))
    cat_id: Mapped[str] = mapped_column(String(50))
    store_id: Mapped[str] = mapped_column(String(50))
    state_id: Mapped[str] = mapped_column(String(50))
    d: Mapped[str] = mapped_column(String(10))
    sales: Mapped[int | None] = mapped_column(Integer, nullable=True)
    item_store_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
