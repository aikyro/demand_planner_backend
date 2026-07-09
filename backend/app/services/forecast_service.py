import json
import uuid
from datetime import datetime, timezone
from sqlalchemy import select, func, distinct
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import ForecastSession, Forecast
from app.models import ApprovalHistory


def session_meta(sess: ForecastSession) -> dict:
    """Generation metadata (dataset/horizon/model/counts) lives in the JSON
    ``notes`` field — the table has no dedicated columns for it."""
    try:
        meta = json.loads(sess.notes) if sess.notes else {}
    except (TypeError, ValueError):
        meta = {}
    return meta if isinstance(meta, dict) else {}


class ForecastService:
    def __init__(self, db: AsyncSession, company_id: str):
        self.db = db
        self.company_id = company_id

    async def create_session(self, data, user_id: str) -> ForecastSession:
        sid = uuid.uuid4().hex
        sess = ForecastSession(
            session_id=sid, id=uuid.uuid4().hex[:12],
            company_id=self.company_id, status="draft", generated_by=user_id,
            notes=json.dumps({
                "dataset_name": data.dataset_name,
                "horizon": data.horizon,
                "aggregation": data.aggregation,
            }),
        )
        self.db.add(sess)
        await self.db.flush()
        return sess

    async def get_session(self, session_id: str) -> ForecastSession | None:
        return (
            await self.db.execute(
                select(ForecastSession).where(
                    ForecastSession.session_id == session_id,
                    ForecastSession.company_id == self.company_id,
                )
            )
        ).scalar_one_or_none()

    async def list_sessions(self):
        return (
            await self.db.execute(
                select(ForecastSession)
                .where(ForecastSession.company_id == self.company_id)
                .order_by(ForecastSession.created_at.desc())
            )
        ).scalars().all()

    async def session_counts(self, session_id: str) -> tuple[int, int]:
        """(distinct item count, forecast row count) for a session."""
        row = (
            await self.db.execute(
                select(
                    func.count(distinct(Forecast.item_id)),
                    func.count(Forecast.id),
                ).where(
                    Forecast.company_id == self.company_id,
                    Forecast.session_id == session_id,
                )
            )
        ).one()
        return int(row[0] or 0), int(row[1] or 0)

    async def forecast_rows(self, session_id: str, item_id: str | None = None):
        stmt = select(Forecast).where(
            Forecast.company_id == self.company_id,
            Forecast.session_id == session_id,
        )
        if item_id:
            stmt = stmt.where(Forecast.item_id == item_id)
        return (await self.db.execute(stmt.order_by(Forecast.date))).scalars().all()

    async def publish(self, session_id: str, user_id: str) -> ForecastSession:
        sess = await self.get_session(session_id)
        if not sess:
            raise ValueError("Session not found")
        sess.status = "published"
        sess.published_at = datetime.now(timezone.utc)
        self.db.add(ApprovalHistory(
            company_id=self.company_id, entity_type="forecast",
            entity_id=session_id, action="published", user_id=user_id,
        ))
        await self.db.flush()
        return sess

    async def set_status(
        self,
        session_id: str,
        user_id: str,
        new_status: str,
        notes: str | None,
    ) -> ForecastSession:
        """Flip a session to ``new_status`` and merge an optional user note.

        Status transitions:
          - new_status == "published" sets ``published_at`` if not already set
            (we never null out the first-publish timestamp on draft flips).
          - new_status == "draft" is always allowed and is itself a valid state.

        Note handling:
          - ``notes is None``      → leave any existing user_notes untouched.
          - ``notes.strip() == ""`` → drop the user_notes key (clear).
          - otherwise              → store under meta["user_notes"].

        An ``ApprovalHistory`` row is written with action="status_change" so
        the audit log distinguishes manual flips from the publish() flow.
        """
        sess = await self.get_session(session_id)
        if not sess:
            raise ValueError("Session not found")

        old_status = sess.status
        sess.status = new_status

        if new_status == "published" and sess.published_at is None:
            sess.published_at = datetime.now(timezone.utc)

        # Merge user note into the JSON notes blob without overwriting other keys.
        meta = session_meta(sess)
        if notes is not None:
            stripped = notes.strip()
            if stripped:
                meta["user_notes"] = stripped
            else:
                meta.pop("user_notes", None)
            sess.notes = json.dumps(meta) if meta else None

        # old_value/new_value are JSONB dicts on ApprovalHistory — wrap the
        # status as {"status": "..."} so the audit log stays self-describing.
        self.db.add(ApprovalHistory(
            company_id=self.company_id, entity_type="forecast",
            entity_id=session_id, action="status_change", user_id=user_id,
            old_value={"status": old_status},
            new_value={"status": new_status},
            comments=notes.strip() if notes and notes.strip() else None,
        ))
        await self.db.flush()
        return sess

    async def mark_generated(self, session_id: str, summary: dict):
        sess = await self.get_session(session_id)
        if not sess:
            return
        meta = session_meta(sess)
        meta.update({
            "model_used": summary.get("model_used"),
            "sku_count": summary.get("sku_count", 0),
            "row_count": summary.get("row_count", 0),
            "metrics": summary.get("metrics"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        })
        sess.notes = json.dumps(meta)
        await self.db.flush()
