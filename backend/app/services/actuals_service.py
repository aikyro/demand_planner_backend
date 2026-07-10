"""Ingest actual values (CSV) against an existing forecast session.

Actuals are what make accuracy/bias/MAPE real: they are joined to forecasts on
(session_id, company_id, item_id, date) by the dashboard service.
"""
import csv
import io
import uuid
from datetime import date as date_cls

from sqlalchemy import select, func, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Actual, ForecastSession, Forecast
from app.services import redis_service

MAX_ERRORS = 50
REQUIRED_COLUMNS = {"item_id", "date", "actual_value"}


class ActualsService:
    def __init__(self, db: AsyncSession, company_id: str):
        self.db = db
        self.company_id = company_id

    async def _session_exists(self, session_id: str) -> bool:
        found = (
            await self.db.execute(
                select(func.count())
                .select_from(ForecastSession)
                .where(
                    ForecastSession.company_id == self.company_id,
                    ForecastSession.session_id == session_id,
                )
            )
        ).scalar_one()
        return bool(found)

    async def _forecast_item_ids(self, session_id: str) -> set[str]:
        rows = (
            await self.db.execute(
                select(distinct(Forecast.item_id)).where(
                    Forecast.company_id == self.company_id,
                    Forecast.session_id == session_id,
                    Forecast.item_id.isnot(None),
                )
            )
        ).scalars().all()
        return {r for r in rows if r}

    async def upload_csv(self, session_id: str, content: bytes) -> dict:
        """Parse a CSV of actuals and bulk-insert rows for a session.

        Raises ValueError for caller-facing 4xx conditions (bad session / headers).
        """
        if not await self._session_exists(session_id):
            raise ValueError(f"Forecast session '{session_id}' not found for this company")

        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("latin-1")
        reader = csv.DictReader(io.StringIO(text))

        headers = {(h or "").strip() for h in (reader.fieldnames or [])}
        missing = REQUIRED_COLUMNS - headers
        if missing:
            raise ValueError(
                f"CSV missing required column(s): {', '.join(sorted(missing))}. "
                f"Expected: item_id, date, actual_value"
            )

        forecast_items = await self._forecast_item_ids(session_id)

        rows: list[dict] = []
        errors: list[str] = []
        skipped = 0
        matched = 0

        for line_no, raw in enumerate(reader, start=2):  # header is line 1
            item_id = (raw.get("item_id") or "").strip()
            date_str = (raw.get("date") or "").strip()
            value_str = (raw.get("actual_value") or "").strip()

            if not item_id or not date_str or value_str == "":
                skipped += 1
                if len(errors) < MAX_ERRORS:
                    errors.append(f"Line {line_no}: missing item_id/date/actual_value")
                continue
            try:
                d = date_cls.fromisoformat(date_str)
            except ValueError:
                skipped += 1
                if len(errors) < MAX_ERRORS:
                    errors.append(f"Line {line_no}: invalid date '{date_str}' (expected YYYY-MM-DD)")
                continue
            try:
                value = float(value_str)
            except ValueError:
                skipped += 1
                if len(errors) < MAX_ERRORS:
                    errors.append(f"Line {line_no}: invalid actual_value '{value_str}'")
                continue

            if item_id in forecast_items:
                matched += 1
            rows.append({
                "id": uuid.uuid4().hex,
                "session_id": session_id,
                "company_id": self.company_id,
                "item_id": item_id,
                "date": d,
                "actual_value": value,
            })

        if rows:
            await self.db.execute(Actual.__table__.insert(), rows)
            await self.db.commit()
            # New actuals change accuracy figures for this session (and the
            # cross-session aggregates) — leave other sessions cached.
            await redis_service.invalidate_session(self.company_id, session_id)

        return {
            "uploaded": len(rows),
            "skipped": skipped,
            "session_id": session_id,
            "matched_items": matched,
            "errors": errors,
        }
