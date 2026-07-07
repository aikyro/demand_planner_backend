"""Generated-files access: list forecast sessions and expose the ADK-produced
tables (modeling_data / forecasts) for preview and CSV download.

modeling_data's dynamic columns are not declared on the ORM model, so preview
and export use parameterized raw SQL over a whitelisted table name.
"""
import csv
import io
from typing import AsyncIterator

from sqlalchemy import select, func, distinct, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ForecastSession, Forecast, ModelingData, Actual

# Whitelist: user-supplied "type" → real table. Never interpolate user input.
TABLES = {"modeling_data": "modeling_data", "forecasts": "forecasts", "actuals": "actuals"}

PREVIEW_ROWS = 10
EXPORT_BATCH = 5000
# Internal/metadata columns hidden from preview and export.
HIDDEN_COLUMNS = {"company_id"}


class GeneratedService:
    def __init__(self, db: AsyncSession, company_id: str):
        self.db = db
        self.company_id = company_id

    async def list_sessions(self, status: str | None, page: int, page_size: int) -> dict:
        conds = [ForecastSession.company_id == self.company_id]
        if status:
            conds.append(ForecastSession.status == status)

        total = (
            await self.db.execute(
                select(func.count()).select_from(ForecastSession).where(*conds)
            )
        ).scalar_one()

        sessions = (
            await self.db.execute(
                select(ForecastSession)
                .where(*conds)
                .order_by(ForecastSession.created_at.desc())
                .offset((max(page, 1) - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()

        items = []
        for s in sessions:
            item_count, row_count, model_used = (
                await self.db.execute(
                    select(
                        func.count(distinct(Forecast.item_id)),
                        func.count(Forecast.id),
                        func.max(Forecast.model_used),
                    ).where(
                        Forecast.company_id == self.company_id,
                        Forecast.session_id == s.session_id,
                    )
                )
            ).one()
            modeling_rows = (
                await self.db.execute(
                    select(func.count(ModelingData.id)).where(
                        ModelingData.company_id == self.company_id,
                        ModelingData.session_id == s.session_id,
                    )
                )
            ).scalar_one()
            actuals_rows = (
                await self.db.execute(
                    select(func.count(Actual.id)).where(
                        Actual.company_id == self.company_id,
                        Actual.session_id == s.session_id,
                    )
                )
            ).scalar_one()
            items.append({
                "session_id": s.session_id,
                "status": s.status,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "published_at": s.published_at.isoformat() if s.published_at else None,
                "generated_by": s.generated_by,
                "item_count": int(item_count or 0),
                "forecast_rows": int(row_count or 0),
                "modeling_rows": int(modeling_rows or 0),
                "actuals_rows": int(actuals_rows or 0),
                "model_used": model_used,
            })
        return {"total": int(total), "page": page, "page_size": page_size, "items": items}

    async def _assert_session(self, session_id: str) -> None:
        found = (
            await self.db.execute(
                select(func.count()).select_from(ForecastSession).where(
                    ForecastSession.company_id == self.company_id,
                    ForecastSession.session_id == session_id,
                )
            )
        ).scalar_one()
        if not found:
            raise ValueError(f"Session '{session_id}' not found for this company")

    async def preview(self, session_id: str, table_type: str) -> dict:
        """Column names + first N rows of a generated table for one session."""
        table = TABLES.get(table_type)
        if not table:
            raise ValueError(f"Unknown type '{table_type}' (expected: {', '.join(TABLES)})")
        await self._assert_session(session_id)

        result = await self.db.execute(
            text(f"SELECT * FROM {table} WHERE session_id = :sid AND company_id = :cid LIMIT :lim"),  # noqa: S608 — table from whitelist
            {"sid": session_id, "cid": self.company_id, "lim": PREVIEW_ROWS},
        )
        all_cols = list(result.keys())
        cols = [c for c in all_cols if c not in HIDDEN_COLUMNS]
        rows = [
            {c: (str(v) if v is not None else None) for c, v in zip(all_cols, row) if c not in HIDDEN_COLUMNS}
            for row in result.fetchall()
        ]
        return {"columns": cols, "rows": rows}

    async def export_csv(
        self, session_id: str, table_type: str, rename: dict[str, str] | None = None,
    ) -> AsyncIterator[str]:
        """Yield CSV text chunks for a full generated table, batched by primary-key-less offset.

        `rename` maps original column names to export header aliases.
        """
        table = TABLES.get(table_type)
        if not table:
            raise ValueError(f"Unknown type '{table_type}' (expected: {', '.join(TABLES)})")
        await self._assert_session(session_id)
        rename = rename or {}

        offset = 0
        wrote_header = False
        col_index: list[int] = []
        while True:
            result = await self.db.execute(
                text(
                    f"SELECT * FROM {table} WHERE session_id = :sid AND company_id = :cid "  # noqa: S608 — table from whitelist
                    "ORDER BY id LIMIT :lim OFFSET :off"
                ),
                {"sid": session_id, "cid": self.company_id, "lim": EXPORT_BATCH, "off": offset},
            )
            rows = result.fetchall()
            buf = io.StringIO()
            writer = csv.writer(buf)
            if not wrote_header:
                all_cols = list(result.keys())
                col_index = [i for i, c in enumerate(all_cols) if c not in HIDDEN_COLUMNS]
                writer.writerow([rename.get(all_cols[i], all_cols[i]) for i in col_index])
                wrote_header = True
            for row in rows:
                writer.writerow([row[i] for i in col_index])
            yield buf.getvalue()
            if len(rows) < EXPORT_BATCH:
                break
            offset += EXPORT_BATCH

    async def forecast_rows(self, session_id: str, page: int, page_size: int) -> dict:
        """Paginated forecast rows for the override editor (id, item, date, value)."""
        await self._assert_session(session_id)
        conds = [
            Forecast.company_id == self.company_id,
            Forecast.session_id == session_id,
        ]
        total = (
            await self.db.execute(select(func.count()).select_from(Forecast).where(*conds))
        ).scalar_one()
        rows = (
            await self.db.execute(
                select(Forecast)
                .where(*conds)
                .order_by(Forecast.item_id, Forecast.date)
                .offset((max(page, 1) - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return {
            "total": int(total),
            "page": page,
            "page_size": page_size,
            "items": [
                {
                    "id": r.id,
                    "item_id": r.item_id,
                    "date": r.date.isoformat() if r.date else None,
                    "predictions": float(r.predictions) if r.predictions is not None else None,
                    "model_used": r.model_used,
                }
                for r in rows
            ],
        }
