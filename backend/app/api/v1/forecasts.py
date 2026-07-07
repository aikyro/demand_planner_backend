from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.core.deps import get_current_user, min_role, CurrentUser
from app.core import job_status
from app.schemas.forecasts import (
    GenerateIn, GenerateOut, SessionOut, StatusOut, ForecastRowOut,
)
from app.services.forecast_service import ForecastService, session_meta
from app.services import redis_service
from app.tasks.forecast_tasks import generate_forecast

router = APIRouter(prefix="/forecasts", tags=["forecasts"])


def _sess_out(s) -> SessionOut:
    meta = session_meta(s)
    return SessionOut(
        session_id=s.session_id, status=s.status, generated_by=s.generated_by,
        dataset_name=meta.get("dataset_name"), horizon=meta.get("horizon"),
        aggregation=meta.get("aggregation"), model_used=meta.get("model_used"),
        sku_count=meta.get("sku_count") or 0, row_count=meta.get("row_count") or 0,
        metrics=meta.get("metrics"), generated_at=meta.get("generated_at"),
        created_at=s.created_at.isoformat() if s.created_at else None,
        published_at=s.published_at.isoformat() if s.published_at else None,
    )


@router.post("/generate", response_model=GenerateOut)
async def generate(data: GenerateIn, user: CurrentUser = Depends(min_role("planner")),
                   db: AsyncSession = Depends(get_db)):
    svc = ForecastService(db, user.company_id)
    sess = await svc.create_session(data, user.id)
    await db.commit()
    await job_status.set_status(sess.session_id, job_status.RUNNING)
    generate_forecast.delay(
        sess.session_id, user.company_id, data.aggregation,
        data.horizon, data.mapping, data.dataset_name,
    )
    return GenerateOut(session_id=sess.session_id, status="running")


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(user: CurrentUser = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    return [_sess_out(s) for s in await ForecastService(db, user.company_id).list_sessions()]


@router.get("/sessions/{session_id}", response_model=SessionOut)
async def get_session(session_id: str, user: CurrentUser = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    s = await ForecastService(db, user.company_id).get_session(session_id)
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    return _sess_out(s)


@router.get("/sessions/{session_id}/status", response_model=StatusOut)
async def get_status(session_id: str, user: CurrentUser = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    st = await job_status.get_status(session_id)
    if st is None:
        s = await ForecastService(db, user.company_id).get_session(session_id)
        st = (s.status if s else "unknown")
    return StatusOut(session_id=session_id, status=st)


@router.get("", response_model=list[ForecastRowOut])
async def list_forecasts(session_id: str = Query(...), item_id: str | None = Query(None),
                         user: CurrentUser = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    rows = await ForecastService(db, user.company_id).forecast_rows(session_id, item_id)
    return [
        ForecastRowOut(
            item_id=r.item_id, date=r.date.isoformat() if r.date else None,
            predictions=float(r.predictions) if r.predictions is not None else None,
            quantile_0_1=float(r.quantile_0_1) if r.quantile_0_1 is not None else None,
            quantile_0_9=float(r.quantile_0_9) if r.quantile_0_9 is not None else None,
            model_used=r.model_used,
        ) for r in rows
    ]


@router.post("/sessions/{session_id}/publish", response_model=SessionOut)
async def publish(session_id: str, user: CurrentUser = Depends(min_role("planner")),
                  db: AsyncSession = Depends(get_db)):
    try:
        s = await ForecastService(db, user.company_id).publish(session_id, user.id)
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    await db.commit()
    # Newly published data changes every dashboard aggregate — drop the company cache.
    await redis_service.invalidate_company(user.company_id)
    return _sess_out(s)
