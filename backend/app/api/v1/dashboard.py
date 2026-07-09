from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.core.deps import get_current_user, min_role, CurrentUser
from app.services.dashboard_service import DashboardService
from app.services.override_service import OverrideService
from fastapi import HTTPException, status
from app.schemas.dashboard import (
    ExecutiveKpisOut, DashboardFilterOptions, OperationalMetricsOut, DistributionOut,
    ProductDetailOut, ProductOverrideIn,
)
from app.schemas.overrides import OverrideIn, OverrideOut

router = APIRouter(tags=["dashboard"])


@router.get("/kpis")
async def kpis(
    category: str | None = Query(None), brand: str | None = Query(None),
    state: str | None = Query(None), region: str | None = Query(None),
    channel: str | None = Query(None),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    filters = {k: v for k, v in dict(
        category=category, brand=brand, state=state, region=region, channel=channel
    ).items() if v}
    return await DashboardService(db, user.company_id).kpis(filters)


@router.get("/filters")
async def filters(user: CurrentUser = Depends(get_current_user),
                  db: AsyncSession = Depends(get_db)):
    return await DashboardService(db, user.company_id).filters()


@router.get("/dashboard/executive", response_model=ExecutiveKpisOut)
async def executive(
    item_id: list[str] | None = Query(None, description="Filter to one or more product item_ids"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    session_id: str | None = Query(None),
    category: str | None = Query(None),
    brand: str | None = Query(None),
    state: str | None = Query(None),
    store: str | None = Query(None),
    channel: str | None = Query(None),
    horizon: str | None = Query(None),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Executive KPIs computed from the forecasts + actuals tables, cached in Redis.

    All results are scoped to the caller's company_id (row-level isolation).
    """
    return await DashboardService(db, user.company_id).executive_kpis(
        item_ids=item_id,
        date_from=date_from,
        date_to=date_to,
        session_id=session_id,
        category=category,
        brand=brand,
        state=state,
        store=store,
        channel=channel,
        horizon=horizon,
    )


@router.get("/dashboard/operational", response_model=OperationalMetricsOut)
async def operational(
    item_id: list[str] | None = Query(None, description="Filter to one or more product item_ids"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    session_id: str | None = Query(None),
    category: str | None = Query(None),
    brand: str | None = Query(None),
    state: str | None = Query(None),
    store: str | None = Query(None),
    channel: str | None = Query(None),
    sort_by: str = Query("accuracy", pattern="^(accuracy|mape|bias|item_id|points|forecast_total|actual_total)$"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    horizon: str | None = Query(None),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Per-item performance metrics (accuracy / MAPE / bias), sorted & paginated.

    Scoped to the caller's company_id. Only items with matching actuals are
    measurable and therefore included.
    """
    return await DashboardService(db, user.company_id).operational_metrics(
        item_ids=item_id,
        date_from=date_from,
        date_to=date_to,
        session_id=session_id,
        category=category,
        brand=brand,
        state=state,
        store=store,
        channel=channel,
        sort_by=sort_by,
        order=order,
        page=page,
        page_size=page_size,
        horizon=horizon,
    )


@router.get("/dashboard/distribution", response_model=DistributionOut)
async def distribution(
    dim: str = Query("cat_id", pattern="^(cat_id|dept_id|store_id|state_id|item_id)$"),
    session_id: str | None = Query(None),
    category: str | None = Query(None),
    brand: str | None = Query(None),
    state: str | None = Query(None),
    store: str | None = Query(None),
    channel: str | None = Query(None),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sales-volume share by dimension + Pareto stats + top/bottom products,
    from the modeling_data table (ADK-generated columns)."""
    try:
        return await DashboardService(db, user.company_id).distribution(
            dim=dim,
            session_id=session_id,
            category=category,
            brand=brand,
            state=state,
            store=store,
            channel=channel,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.get("/dashboard/filters", response_model=DashboardFilterOptions)
async def dashboard_filter_options(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Distinct product item_ids and recent sessions for dashboard filter dropdowns."""
    return await DashboardService(db, user.company_id).executive_filter_options()


@router.get("/dashboard/product/{item_id}", response_model=ProductDetailOut)
async def product_detail(
    item_id: str,
    session_id: str | None = Query(None, description="Forecast session; defaults to the item's latest"),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Product metadata + per-date forecast/baseline/actual/override history.

    Backs the Product Detail page and Forecast Editor. Company-scoped; cached
    per (company, session, item).
    """
    try:
        return await DashboardService(db, user.company_id).product_detail(item_id, session_id)
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))


@router.post("/dashboard/product/override", response_model=OverrideOut)
async def product_override(
    data: ProductOverrideIn,
    user: CurrentUser = Depends(min_role("analyst")),
    db: AsyncSession = Depends(get_db),
):
    """Per-date forecast override for the Forecast Editor.

    Resolves (item_id, session_id, date) → forecast row, then runs the standard
    override workflow: audit row, role-based approval tier, write-back to
    forecasts on approval, and selective Redis invalidation.
    """
    try:
        d = date.fromisoformat(data.date)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid date '{data.date}' (expected YYYY-MM-DD)")

    fid = await DashboardService(db, user.company_id).resolve_forecast_id(
        data.item_id, data.session_id, d
    )
    if not fid:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No forecast for item '{data.item_id}' on {data.date} in session '{data.session_id}'",
        )

    from app.api.v1.overrides import _out  # reuse the canonical serializer
    try:
        ov, _notify = await OverrideService(db, user.company_id).create(
            OverrideIn(forecast_id=fid, override_value=data.override_value, reason=data.reason),
            user.id, user.role,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    await db.commit()
    return _out(ov)


@router.get("/dashboard/registry")
async def registry(
    item_id: list[str] | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    session_id: str | None = Query(None),
    category: str | None = Query(None),
    brand: str | None = Query(None),
    state: str | None = Query(None),
    store: str | None = Query(None),
    channel: str | None = Query(None),
    sort_by: str = Query("accuracy"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    horizon: str | None = Query(None),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await DashboardService(db, user.company_id).registry(
        item_ids=item_id,
        date_from=date_from,
        date_to=date_to,
        session_id=session_id,
        category=category,
        brand=brand,
        state=state,
        store=store,
        channel=channel,
        sort_by=sort_by,
        order=order,
        page=page,
        page_size=page_size,
        horizon=horizon,
    )


@router.get("/dashboard/segmentation")
async def segmentation(
    item_id: list[str] | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    session_id: str | None = Query(None),
    category: str | None = Query(None),
    brand: str | None = Query(None),
    state: str | None = Query(None),
    store: str | None = Query(None),
    channel: str | None = Query(None),
    horizon: str | None = Query(None),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await DashboardService(db, user.company_id).segmentation(
        item_ids=item_id,
        date_from=date_from,
        date_to=date_to,
        session_id=session_id,
        category=category,
        brand=brand,
        state=state,
        store=store,
        channel=channel,
        horizon=horizon,
    )
