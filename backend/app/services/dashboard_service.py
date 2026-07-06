import json
from collections import defaultdict
from statistics import mean, pstdev
from datetime import date as date_cls
from sqlalchemy import select, func, and_, distinct, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import DataUpload, Lookup, Forecast, Actual, ForecastSession
from app.core.redis import redis_client
from app.core.config import settings
from app.services import redis_service


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


class DashboardService:
    def __init__(self, db: AsyncSession, company_id: str):
        self.db = db
        self.company_id = company_id

    async def _all_rows(self) -> list[dict]:
        uploads = (
            await self.db.execute(
                select(DataUpload).where(DataUpload.company_id == self.company_id)
            )
        ).scalars().all()
        rows: list[dict] = []
        for u in uploads:
            rows.extend(u.data or [])
        return rows

    async def _lookup(self) -> list[Lookup]:
        return (
            await self.db.execute(select(Lookup).where(Lookup.company_id == self.company_id))
        ).scalars().all()

    def _match(self, row, lk_by_product, filters) -> bool:
        if not filters:
            return True
        meta = lk_by_product.get(str(row.get("product_id")))
        if not meta:
            return False
        for k, v in filters.items():
            if v and getattr(meta, k, None) != v:
                return False
        return True

    async def kpis(self, filters: dict) -> dict:
        cache_key = f"kpis:{self.company_id}:{json.dumps(filters, sort_keys=True)}"
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)

        rows = await self._all_rows()
        lookup = await self._lookup()
        lk_by_product = {l.product_id: l for l in lookup}

        total_qty = total_rev = 0.0
        skus, locations = set(), set()
        monthly = defaultdict(float)
        for r in rows:
            if not self._match(r, lk_by_product, filters):
                continue
            total_qty += _num(r.get("quantity"))
            total_rev += _num(r.get("revenue"))
            if r.get("product_id"):
                skus.add(str(r["product_id"]))
            if r.get("location_id"):
                locations.add(str(r["location_id"]))
            d = str(r.get("date") or "")[:7]
            if d:
                monthly[d] += _num(r.get("quantity"))

        result = {
            "total_quantity": round(total_qty, 2),
            "total_revenue": round(total_rev, 2),
            "sku_count": len(skus),
            "location_count": len(locations) or len({l.location_id for l in lookup}),
            "monthly_volume": [
                {"month": m, "quantity": round(q, 2)} for m, q in sorted(monthly.items())
            ],
        }
        await redis_client.setex(cache_key, settings.KPI_CACHE_TTL, json.dumps(result))
        return result

    async def filters(self) -> dict:
        lookup = await self._lookup()
        def uniq(attr):
            return sorted({getattr(l, attr) for l in lookup if getattr(l, attr)})
        return {
            "category": uniq("category"),
            "brand": uniq("brand"),
            "state": uniq("state"),
            "region": uniq("region"),
            "channel": uniq("channel"),
            "location_id": uniq("location_id"),
        }

    # ------------------------------------------------------------------
    # Executive dashboard (forecast-table driven: forecasts + actuals)
    # ------------------------------------------------------------------
    def _forecast_conds(self, item_ids, date_from, date_to, session_id):
        conds = [Forecast.company_id == self.company_id]
        if session_id:
            conds.append(Forecast.session_id == session_id)
        if item_ids:
            conds.append(Forecast.item_id.in_(item_ids))
        if date_from:
            conds.append(Forecast.date >= date_from)
        if date_to:
            conds.append(Forecast.date <= date_to)
        return conds

    def _actual_conds(self, item_ids, date_from, date_to, session_id):
        conds = [Actual.company_id == self.company_id]
        if session_id:
            conds.append(Actual.session_id == session_id)
        if item_ids:
            conds.append(Actual.item_id.in_(item_ids))
        if date_from:
            conds.append(Actual.date >= date_from)
        if date_to:
            conds.append(Actual.date <= date_to)
        return conds

    async def executive_kpis(
        self,
        item_ids: list[str] | None = None,
        date_from: date_cls | None = None,
        date_to: date_cls | None = None,
        session_id: str | None = None,
    ) -> dict:
        cache_filters = {
            "item_ids": sorted(item_ids) if item_ids else None,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "session_id": session_id,
        }
        key = redis_service.cache_key(
            self.company_id, "executive",
            json.dumps(cache_filters, sort_keys=True),
        )
        cached = await redis_service.get_json(key)
        if cached is not None:
            return cached

        fc = self._forecast_conds(item_ids, date_from, date_to, session_id)

        # Forecast-side aggregates.
        total_forecasts, active_items, total_predicted = (
            await self.db.execute(
                select(
                    func.count(Forecast.id),
                    func.count(distinct(Forecast.item_id)),
                    func.coalesce(func.sum(Forecast.predictions), 0),
                ).where(and_(*fc))
            )
        ).one()

        # Accuracy / bias at the (session, item, date) grain via join to actuals.
        join_on = and_(
            Forecast.session_id == Actual.session_id,
            Forecast.company_id == Actual.company_id,
            Forecast.item_id == Actual.item_id,
            Forecast.date == Actual.date,
        )
        sum_abs_err, sum_actual, sum_err, matched = (
            await self.db.execute(
                select(
                    func.coalesce(func.sum(func.abs(Forecast.predictions - Actual.actual_value)), 0),
                    func.coalesce(func.sum(Actual.actual_value), 0),
                    func.coalesce(func.sum(Forecast.predictions - Actual.actual_value), 0),
                    func.count(),
                )
                .select_from(Forecast)
                .join(Actual, join_on)
                .where(and_(*fc))
            )
        ).one()

        sum_actual = float(sum_actual)
        accuracy = (
            round(max(0.0, (1 - float(sum_abs_err) / sum_actual) * 100), 2)
            if sum_actual else None
        )
        bias_pct = round(float(sum_err) / sum_actual * 100, 2) if sum_actual else None

        # Forecast-vs-actual trend over time.
        fc_trend = (
            await self.db.execute(
                select(Forecast.date, func.coalesce(func.sum(Forecast.predictions), 0))
                .where(and_(*fc))
                .group_by(Forecast.date)
            )
        ).all()
        ac_trend = (
            await self.db.execute(
                select(Actual.date, func.coalesce(func.sum(Actual.actual_value), 0))
                .where(and_(*self._actual_conds(item_ids, date_from, date_to, session_id)))
                .group_by(Actual.date)
            )
        ).all()

        merged: dict = {}
        for d, v in fc_trend:
            if d is None:
                continue
            merged.setdefault(d, {})["forecast"] = round(float(v or 0), 2)
        for d, v in ac_trend:
            if d is None:
                continue
            merged.setdefault(d, {})["actual"] = round(float(v or 0), 2)
        trend = [
            {
                "date": d.isoformat(),
                "forecast": vals.get("forecast", 0.0),
                "actual": vals.get("actual"),
            }
            for d, vals in sorted(merged.items())
        ]

        # Recent sessions + total session count.
        session_count = (
            await self.db.execute(
                select(func.count())
                .select_from(ForecastSession)
                .where(ForecastSession.company_id == self.company_id)
            )
        ).scalar_one()
        sessions = (
            await self.db.execute(
                select(ForecastSession)
                .where(ForecastSession.company_id == self.company_id)
                .order_by(ForecastSession.created_at.desc())
                .limit(5)
            )
        ).scalars().all()
        recent = [
            {
                "session_id": s.session_id,
                "status": s.status,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in sessions
        ]

        result = {
            "total_forecasts": int(total_forecasts or 0),
            "active_items": int(active_items or 0),
            "total_predicted": round(float(total_predicted or 0), 2),
            "total_actual": round(sum_actual, 2),
            "overall_accuracy": accuracy,
            "bias_pct": bias_pct,
            "matched_points": int(matched or 0),
            "session_count": int(session_count or 0),
            "trend": trend,
            "recent_sessions": recent,
        }
        await redis_service.set_json(key, result, settings.DASHBOARD_CACHE_TTL)
        return result

    async def operational_metrics(
        self,
        item_ids: list[str] | None = None,
        date_from: date_cls | None = None,
        date_to: date_cls | None = None,
        session_id: str | None = None,
        sort_by: str = "accuracy",
        order: str = "asc",
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        """Per-item performance metrics (accuracy / MAPE / bias) from forecasts ⋈ actuals.

        Only items that have matching actuals are measurable, so the table is
        scoped to those. Aggregation is one row per item_id (bounded by the
        product catalogue), sorted and paginated in-process.
        """
        cache_filters = {
            "item_ids": sorted(item_ids) if item_ids else None,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "session_id": session_id,
            "sort_by": sort_by,
            "order": order,
            "page": page,
            "page_size": page_size,
        }
        key = redis_service.cache_key(
            self.company_id, "operational",
            json.dumps(cache_filters, sort_keys=True),
        )
        cached = await redis_service.get_json(key)
        if cached is not None:
            return cached

        fc = self._forecast_conds(item_ids, date_from, date_to, session_id)
        join_on = and_(
            Forecast.session_id == Actual.session_id,
            Forecast.company_id == Actual.company_id,
            Forecast.item_id == Actual.item_id,
            Forecast.date == Actual.date,
        )
        rows = (
            await self.db.execute(
                select(
                    Forecast.item_id,
                    func.count().label("points"),
                    func.coalesce(func.sum(func.abs(Forecast.predictions - Actual.actual_value)), 0),
                    func.coalesce(func.sum(Actual.actual_value), 0),
                    func.coalesce(func.sum(Forecast.predictions - Actual.actual_value), 0),
                    func.coalesce(func.sum(Forecast.predictions), 0),
                )
                .select_from(Forecast)
                .join(Actual, join_on)
                .where(and_(*fc))
                .group_by(Forecast.item_id)
            )
        ).all()

        items: list[dict] = []
        for item_id, points, abs_err, actual_sum, err_sum, pred_sum in rows:
            actual_sum = float(actual_sum)
            mape = round(float(abs_err) / actual_sum * 100, 2) if actual_sum else None
            accuracy = round(max(0.0, 100 - mape), 2) if mape is not None else None
            bias = round(float(err_sum) / actual_sum * 100, 2) if actual_sum else None
            items.append({
                "item_id": item_id,
                "points": int(points or 0),
                "forecast_total": round(float(pred_sum or 0), 2),
                "actual_total": round(actual_sum, 2),
                "accuracy": accuracy,
                "mape": mape,
                "bias": bias,
            })

        # Summary: dispersion of bias across measured items.
        biases = [i["bias"] for i in items if i["bias"] is not None]
        summary = {
            "measured_items": len(items),
            "mean_bias": round(mean(biases), 2) if biases else None,
            "std_bias": round(pstdev(biases), 2) if len(biases) > 1 else (0.0 if biases else None),
        }

        # Worst 10 by accuracy (nulls treated as worst).
        worst_items = sorted(
            items, key=lambda i: (i["accuracy"] is not None, i["accuracy"] if i["accuracy"] is not None else 0)
        )[:10]

        # Sort the full list for the paginated table, keeping null metrics last
        # regardless of direction.
        sort_field = sort_by if sort_by in {"accuracy", "mape", "bias", "item_id", "points", "forecast_total", "actual_total"} else "accuracy"
        reverse = order == "desc"
        non_null = [i for i in items if i[sort_field] is not None]
        nulls = [i for i in items if i[sort_field] is None]
        non_null.sort(key=lambda i: i[sort_field], reverse=reverse)
        items = non_null + nulls

        total = len(items)
        start = (max(page, 1) - 1) * page_size
        page_items = items[start:start + page_size]

        result = {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": page_items,
            "worst_items": worst_items,
            "summary": summary,
        }
        await redis_service.set_json(key, result, settings.DASHBOARD_CACHE_TTL)
        return result

    # Whitelisted modeling_data dimension columns for distribution queries.
    # These columns are created by the ADK, not declared on the ORM model,
    # so queries go through parameterized raw SQL — never interpolate user input.
    DISTRIBUTION_DIMS = {"cat_id", "dept_id", "store_id", "state_id", "item_id"}

    async def distribution(self, dim: str, session_id: str | None = None) -> dict:
        """Sales-volume share by a modeling_data dimension + Pareto stats +
        top/bottom products. Feeds the executive distribution/Pareto cards."""
        if dim not in self.DISTRIBUTION_DIMS:
            raise ValueError(f"Unsupported dimension '{dim}'")

        key = redis_service.cache_key(
            self.company_id, "distribution", f"{dim}:{session_id or 'all'}"
        )
        cached = await redis_service.get_json(key)
        if cached is not None:
            return cached

        sess_clause = "AND session_id = :session_id" if session_id else ""
        params: dict = {"company_id": self.company_id}
        if session_id:
            params["session_id"] = session_id

        shares = (
            await self.db.execute(
                text(
                    f"""SELECT {dim} AS label, COALESCE(SUM(sales), 0) AS volume
                        FROM modeling_data
                        WHERE company_id = :company_id AND {dim} IS NOT NULL {sess_clause}
                        GROUP BY {dim} ORDER BY volume DESC"""
                ),
                params,
            )
        ).all()
        total_volume = float(sum(float(v or 0) for _, v in shares)) or 0.0
        share_rows = [
            {
                "label": label,
                "volume": round(float(v or 0), 2),
                "share": round(float(v or 0) / total_volume * 100, 2) if total_volume else 0.0,
            }
            for label, v in shares
        ]

        # Pareto over products: share of volume held by the top 20% of items.
        item_rows = (
            await self.db.execute(
                text(
                    f"""SELECT item_id, COALESCE(SUM(sales), 0) AS volume
                        FROM modeling_data
                        WHERE company_id = :company_id AND item_id IS NOT NULL {sess_clause}
                        GROUP BY item_id ORDER BY volume DESC"""
                ),
                params,
            )
        ).all()
        volumes = [float(v or 0) for _, v in item_rows]
        item_total = sum(volumes)
        top_n = max(1, round(len(volumes) * 0.2)) if volumes else 0
        pareto = {
            "item_count": len(volumes),
            "top20_count": top_n,
            "top20_share": round(sum(volumes[:top_n]) / item_total * 100, 2) if item_total else 0.0,
        }

        def product(row) -> dict:
            return {"item_id": row[0], "volume": round(float(row[1] or 0), 2)}

        result = {
            "dim": dim,
            "total_volume": round(total_volume, 2),
            "shares": share_rows[:50],
            "pareto": pareto,
            "top_products": [product(r) for r in item_rows[:5]],
            "bottom_products": [product(r) for r in item_rows[-5:][::-1]] if item_rows else [],
        }
        await redis_service.set_json(key, result, settings.DASHBOARD_CACHE_TTL)
        return result

    async def executive_filter_options(self) -> dict:
        """Distinct item_ids + recent sessions for dashboard filter dropdowns."""
        key = redis_service.cache_key(self.company_id, "filter_options")
        cached = await redis_service.get_json(key)
        if cached is not None:
            return cached

        item_ids = (
            await self.db.execute(
                select(distinct(Forecast.item_id))
                .where(and_(Forecast.company_id == self.company_id, Forecast.item_id.isnot(None)))
                .order_by(Forecast.item_id)
            )
        ).scalars().all()
        sessions = (
            await self.db.execute(
                select(ForecastSession)
                .where(ForecastSession.company_id == self.company_id)
                .order_by(ForecastSession.created_at.desc())
                .limit(50)
            )
        ).scalars().all()
        result = {
            "item_ids": [i for i in item_ids if i],
            "sessions": [
                {
                    "session_id": s.session_id,
                    "status": s.status,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                }
                for s in sessions
            ],
        }
        await redis_service.set_json(key, result, settings.DASHBOARD_REFERENCE_TTL)
        return result
