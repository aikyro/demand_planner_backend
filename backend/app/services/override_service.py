from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Override, Forecast, ApprovalHistory, User
from app.core.deps import ROLE_RANK
from app.services import redis_service


def required_rank(pct: float) -> int:
    """Approval tier → minimum role rank. 0-10 auto, 10-25 planner, >25 admin."""
    pct = abs(pct)
    if pct <= 10:
        return ROLE_RANK["viewer"]    # auto — anyone
    if pct <= 25:
        return ROLE_RANK["planner"]   # manager
    return ROLE_RANK["admin"]         # manager+director / executive


def tier_status(pct: float) -> str:
    """Initial override status for a % change: auto-approved or routed to a tier."""
    pct = abs(pct)
    if pct <= 10:
        return "approved"
    if pct <= 25:
        return "pending_planner"
    return "pending_admin"


def _is_pending(status: str) -> bool:
    # "pending" kept for rows created before tiered statuses existed.
    return status == "pending" or status.startswith("pending_")


class OverrideService:
    def __init__(self, db: AsyncSession, company_id: str):
        self.db = db
        self.company_id = company_id

    async def _forecast(self, fid: str) -> Forecast | None:
        return (await self.db.execute(
            select(Forecast).where(Forecast.id == fid, Forecast.company_id == self.company_id)
        )).scalar_one_or_none()

    async def _get(self, oid: str) -> Override | None:
        return (await self.db.execute(
            select(Override).where(Override.id == oid, Override.company_id == self.company_id)
        )).scalar_one_or_none()

    async def get(self, oid: str) -> Override | None:
        return await self._get(oid)

    async def _admin_email(self) -> str | None:
        u = (await self.db.execute(
            select(User).where(User.company_id == self.company_id, User.role == "admin")
        )).scalars().first()
        return u.email if u else None

    async def create(self, data, user_id: str) -> tuple[Override, str | None]:
        fc = await self._forecast(data.forecast_id)
        if not fc:
            raise ValueError("Forecast not found")
        original = float(fc.predictions or 0)
        pct = ((data.override_value - original) / original * 100) if original else 0.0
        status = tier_status(pct)
        ov = Override(
            company_id=self.company_id, forecast_id=fc.id,
            product_id=fc.item_id or fc.target_name or "unknown",
            user_id=user_id, original_value=original, override_value=data.override_value,
            pct_change=round(pct, 2), reason=data.reason,
            status=status,
        )
        self.db.add(ov)
        await self.db.flush()
        self.db.add(ApprovalHistory(
            company_id=self.company_id, entity_type="override", entity_id=str(ov.id),
            action="created", user_id=user_id,
            old_value={"predictions": original},
            new_value={"override_value": data.override_value, "pct": round(pct, 2)},
        ))
        if status == "approved":
            await self._apply(ov)
            notify_email = None
        else:
            notify_email = await self._admin_email()
        await self.db.flush()
        return ov, notify_email

    async def _apply(self, ov: Override):
        """Write the approved override into the forecasts table and drop caches."""
        fc = await self._forecast(str(ov.forecast_id))
        if fc:
            fc.predictions = ov.override_value
        await redis_service.invalidate_company(self.company_id)

    async def decide(self, oid: str, approver, approve: bool, comments) -> Override:
        ov = await self._get(oid)
        if not ov:
            raise ValueError("Override not found")
        if not _is_pending(ov.status):
            raise ValueError("Override not pending")
        if ROLE_RANK.get(approver.role, -1) < required_rank(float(ov.pct_change or 0)):
            raise ValueError("Insufficient role to approve this change")
        ov.status = "approved" if approve else "rejected"
        ov.approved_by = approver.id
        from datetime import datetime, timezone
        ov.approved_at = datetime.now(timezone.utc)
        if approve:
            await self._apply(ov)
        self.db.add(ApprovalHistory(
            company_id=self.company_id, entity_type="override", entity_id=str(ov.id),
            action="approved" if approve else "rejected", user_id=approver.id,
            comments=comments,
        ))
        await self.db.flush()
        return ov

    async def list(self, status: str | None = None):
        stmt = select(Override).where(Override.company_id == self.company_id)
        if status == "pending":
            # Any pending tier.
            stmt = stmt.where(Override.status.like("pending%"))
        elif status:
            stmt = stmt.where(Override.status == status)
        return (await self.db.execute(stmt.order_by(Override.created_at.desc()))).scalars().all()

    async def list_for_forecast(self, forecast_id: str):
        return (await self.db.execute(
            select(Override)
            .where(Override.company_id == self.company_id, Override.forecast_id == forecast_id)
            .order_by(Override.created_at.desc())
        )).scalars().all()
