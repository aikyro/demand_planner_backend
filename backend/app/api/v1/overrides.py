from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.core.deps import get_current_user, min_role, CurrentUser
from app.schemas.overrides import OverrideIn, OverrideOut, DecisionIn
from app.services.override_service import OverrideService
from app.tasks.email_tasks import notify

router = APIRouter(prefix="/overrides", tags=["overrides"])


def _out(o) -> OverrideOut:
    return OverrideOut(
        id=str(o.id), forecast_id=str(o.forecast_id), product_id=o.product_id,
        original_value=float(o.original_value), override_value=float(o.override_value),
        pct_change=float(o.pct_change) if o.pct_change is not None else None,
        status=o.status, reason=o.reason,
        created_at=o.created_at.isoformat() if o.created_at else None,
        approved_by=str(o.approved_by) if o.approved_by else None,
        approved_at=o.approved_at.isoformat() if o.approved_at else None,
    )


@router.get("", response_model=list[OverrideOut])
async def list_overrides(status_filter: str | None = Query(None, alias="status"),
                         user: CurrentUser = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    return [_out(o) for o in await OverrideService(db, user.company_id).list(status_filter)]


@router.get("/forecast/{forecast_id}", response_model=list[OverrideOut])
async def overrides_for_forecast(forecast_id: str,
                                 user: CurrentUser = Depends(get_current_user),
                                 db: AsyncSession = Depends(get_db)):
    """All overrides recorded against a single forecast row (newest first)."""
    return [_out(o) for o in await OverrideService(db, user.company_id).list_for_forecast(forecast_id)]


@router.get("/{override_id}", response_model=OverrideOut)
async def get_override(override_id: str,
                       user: CurrentUser = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    ov = await OverrideService(db, user.company_id).get(override_id)
    if not ov:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Override not found")
    return _out(ov)


@router.post("", response_model=OverrideOut)
async def create_override(data: OverrideIn, user: CurrentUser = Depends(min_role("analyst")),
                          db: AsyncSession = Depends(get_db)):
    try:
        # Pass user role to determine auto-approval based on role
        ov, notify_email = await OverrideService(db, user.company_id).create(data, user.id, user.role)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    await db.commit()
    if notify_email:
        notify.delay(notify_email, "override_pending", product=ov.product_id,
                     original=float(ov.original_value), override=float(ov.override_value),
                     pct=float(ov.pct_change or 0), reason=ov.reason or "-")
    return _out(ov)


@router.post("/{override_id}/approve", response_model=OverrideOut)
async def approve(override_id: str, data: DecisionIn,
                  user: CurrentUser = Depends(min_role("planner")),
                  db: AsyncSession = Depends(get_db)):
    try:
        ov = await OverrideService(db, user.company_id).decide(override_id, user, True, data.comments)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    await db.commit()
    return _out(ov)


@router.post("/{override_id}/reject", response_model=OverrideOut)
async def reject(override_id: str, data: DecisionIn,
                 user: CurrentUser = Depends(min_role("planner")),
                 db: AsyncSession = Depends(get_db)):
    try:
        ov = await OverrideService(db, user.company_id).decide(override_id, user, False, data.comments)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    await db.commit()
    return _out(ov)
