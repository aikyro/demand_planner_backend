import json
from collections import defaultdict
from statistics import mean, pstdev
from datetime import date as date_cls, timedelta
from sqlalchemy import select, func, and_, distinct, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import DataUpload, Lookup, Forecast, Actual, ForecastSession, Sales
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
        lk_by_product = {l.item_id: l for l in lookup}

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
            "location_count": len(locations) or len({l.store_id for l in lookup}),
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
            "location_id": uniq("store_id"),
        }

    def _apply_lookup_filters(
        self,
        stmt,
        model_cls,
        category: str | None = None,
        brand: str | None = None,
        state: str | None = None,
        store: str | None = None,
        channel: str | None = None,
    ):
        has_filters = any([category, brand, state, store, channel])
        if not has_filters:
            return stmt

        lookup_conds = [
            model_cls.item_id == Lookup.item_id,
            model_cls.company_id == Lookup.company_id,
        ]

        if category and category != "All":
            lookup_conds.append(Lookup.category == category)
        if brand and brand != "All":
            lookup_conds.append(Lookup.brand == brand)
        if state and state != "All":
            lookup_conds.append(Lookup.state == state)
        if store and store != "All":
            lookup_conds.append(Lookup.store_id == store)
        if channel and channel != "All":
            lookup_conds.append(Lookup.channel == channel)

        return stmt.where(
            select(1).select_from(Lookup).where(and_(*lookup_conds)).exists()
        )

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
        category: str | None = None,
        brand: str | None = None,
        state: str | None = None,
        store: str | None = None,
        channel: str | None = None,
        horizon: str | None = None,
    ) -> dict:
        cache_filters = {
            "item_ids": sorted(item_ids) if item_ids else None,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "session_id": session_id,
            "category": category,
            "brand": brand,
            "state": state,
            "store": store,
            "channel": channel,
            "horizon": horizon,
        }
        key = redis_service.cache_key(
            self.company_id, "executive",
            json.dumps(cache_filters, sort_keys=True),
        )
        cached = await redis_service.get_json(key)
        if cached is not None:
            return cached

        if horizon:
            horizon_map = {"L4": 28, "L13": 91, "L26": 182, "L52": 364}
            days_to_subtract = horizon_map.get(horizon)
            if days_to_subtract:
                stmt_max = select(func.max(Forecast.date)).where(Forecast.company_id == self.company_id)
                if session_id:
                    stmt_max = stmt_max.where(Forecast.session_id == session_id)
                max_date = (await self.db.execute(stmt_max)).scalar()
                if max_date:
                    horizon_start = max_date - timedelta(days=days_to_subtract)
                    if date_from:
                        date_from = max(date_from, horizon_start)
                    else:
                        date_from = horizon_start

        fc = self._forecast_conds(item_ids, date_from, date_to, session_id)

        # Forecast-side aggregates.
        stmt_fc = select(
            func.count(Forecast.id),
            func.count(distinct(Forecast.item_id)),
            func.coalesce(func.sum(Forecast.predictions), 0),
        ).where(and_(*fc))
        stmt_fc = self._apply_lookup_filters(stmt_fc, Forecast, category, brand, state, store, channel)
        total_forecasts, active_items, total_predicted = (await self.db.execute(stmt_fc)).one()

        # Accuracy / bias at the (session, item, date) grain via join to actuals.
        join_on = and_(
            Forecast.session_id == Actual.session_id,
            Forecast.company_id == Actual.company_id,
            Forecast.item_id == Actual.item_id,
            Forecast.date == Actual.date,
        )
        stmt_join = (
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
        stmt_join = self._apply_lookup_filters(stmt_join, Forecast, category, brand, state, store, channel)
        sum_abs_err, sum_actual, sum_err, matched = (await self.db.execute(stmt_join)).one()

        sum_actual = float(sum_actual)
        accuracy = (
            round(max(0.0, (1 - float(sum_abs_err) / sum_actual) * 100), 2)
            if sum_actual else None
        )
        bias_pct = round(float(sum_err) / sum_actual * 100, 2) if sum_actual else None

        # Forecast-vs-actual trend over time.
        stmt_fc_trend = (
            select(
                Forecast.date, 
                func.coalesce(func.sum(Forecast.predictions), 0),
                func.coalesce(func.sum(Forecast.original_value), 0)
            )
            .where(and_(*fc))
            .group_by(Forecast.date)
        )
        stmt_fc_trend = self._apply_lookup_filters(stmt_fc_trend, Forecast, category, brand, state, store, channel)
        fc_trend = (await self.db.execute(stmt_fc_trend)).all()

        stmt_ac_trend = (
            select(Actual.date, func.coalesce(func.sum(Actual.actual_value), 0))
            .where(and_(*self._actual_conds(item_ids, date_from, date_to, session_id)))
            .group_by(Actual.date)
        )
        stmt_ac_trend = self._apply_lookup_filters(stmt_ac_trend, Actual, category, brand, state, store, channel)
        ac_trend = (await self.db.execute(stmt_ac_trend)).all()

        merged: dict = {}
        for d, v, pv in fc_trend:
            if d is None:
                continue
            merged.setdefault(d, {})["forecast"] = round(float(v or 0), 2)
            merged[d]["pristine"] = round(float(pv or 0), 2)
        for d, v in ac_trend:
            if d is None:
                continue
            merged.setdefault(d, {})["actual"] = round(float(v or 0), 2)
        trend = [
            {
                "date": d.isoformat(),
                "forecast": vals.get("forecast", 0.0),
                "actual": vals.get("actual"),
                "pristine": vals.get("pristine"),
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
        category: str | None = None,
        brand: str | None = None,
        state: str | None = None,
        store: str | None = None,
        channel: str | None = None,
        sort_by: str = "accuracy",
        order: str = "asc",
        page: int = 1,
        page_size: int = 50,
        horizon: str | None = None,
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
            "category": category,
            "brand": brand,
            "state": state,
            "store": store,
            "channel": channel,
            "sort_by": sort_by,
            "order": order,
            "page": page,
            "page_size": page_size,
            "horizon": horizon,
        }
        key = redis_service.cache_key(
            self.company_id, "operational",
            json.dumps(cache_filters, sort_keys=True),
        )
        cached = await redis_service.get_json(key)
        if cached is not None:
            return cached

        if horizon:
            horizon_map = {"L4": 28, "L13": 91, "L26": 182, "L52": 364}
            days_to_subtract = horizon_map.get(horizon)
            if days_to_subtract:
                stmt_max = select(func.max(Forecast.date)).where(Forecast.company_id == self.company_id)
                if session_id:
                    stmt_max = stmt_max.where(Forecast.session_id == session_id)
                max_date = (await self.db.execute(stmt_max)).scalar()
                if max_date:
                    horizon_start = max_date - timedelta(days=days_to_subtract)
                    if date_from:
                        date_from = max(date_from, horizon_start)
                    else:
                        date_from = horizon_start

        fc = self._forecast_conds(item_ids, date_from, date_to, session_id)
        join_on = and_(
            Forecast.session_id == Actual.session_id,
            Forecast.company_id == Actual.company_id,
            Forecast.item_id == Actual.item_id,
            Forecast.date == Actual.date,
        )
        stmt = (
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
        stmt = self._apply_lookup_filters(stmt, Forecast, category, brand, state, store, channel)
        rows = (await self.db.execute(stmt)).all()

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

    async def distribution(
        self,
        dim: str,
        session_id: str | None = None,
        category: str | None = None,
        brand: str | None = None,
        state: str | None = None,
        store: str | None = None,
        channel: str | None = None,
    ) -> dict:
        """Sales-volume share by a modeling_data dimension + Pareto stats +
        top/bottom products. Feeds the executive distribution/Pareto cards."""
        if dim not in self.DISTRIBUTION_DIMS:
            raise ValueError(f"Unsupported dimension '{dim}'")

        key = redis_service.cache_key(
            self.company_id, "distribution",
            f"{dim}:{session_id or 'all'}:{category or ''}:{brand or ''}:{state or ''}:{store or ''}:{channel or ''}"
        )
        cached = await redis_service.get_json(key)
        if cached is not None:
            return cached

        sess_clause = "AND session_id = :session_id" if session_id else ""
        params: dict = {"company_id": self.company_id}
        if session_id:
            params["session_id"] = session_id

        join_clause = ""
        filter_clauses = []
        has_filters = any([category, brand, state, store, channel])
        if has_filters:
            join_clause = """
                LEFT JOIN lookup ON modeling_data.item_id = lookup.item_id
                                AND modeling_data.company_id = lookup.company_id
                                AND modeling_data.store_id = lookup.store_id
            """
            if category and category != "All":
                filter_clauses.append("AND lookup.category = :category")
                params["category"] = category
            if brand and brand != "All":
                filter_clauses.append("AND lookup.brand = :brand")
                params["brand"] = brand
            if state and state != "All":
                filter_clauses.append("AND lookup.state = :state")
                params["state"] = state
            if store and store != "All":
                filter_clauses.append("AND lookup.store_id = :store")
                params["store"] = store
            if channel and channel != "All":
                filter_clauses.append("AND lookup.channel = :channel")
                params["channel"] = channel

        filter_clause_str = " ".join(filter_clauses)

        shares = (
            await self.db.execute(
                text(
                    f"""SELECT modeling_data.{dim} AS label, COALESCE(SUM(modeling_data.sales), 0) AS volume
                        FROM modeling_data
                        {join_clause}
                        WHERE modeling_data.company_id = :company_id AND modeling_data.{dim} IS NOT NULL {sess_clause} {filter_clause_str}
                        GROUP BY modeling_data.{dim} ORDER BY volume DESC"""
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
                    f"""SELECT modeling_data.item_id, COALESCE(SUM(modeling_data.sales), 0) AS volume
                        FROM modeling_data
                        {join_clause}
                        WHERE modeling_data.company_id = :company_id AND modeling_data.item_id IS NOT NULL {sess_clause} {filter_clause_str}
                        GROUP BY modeling_data.item_id ORDER BY volume DESC"""
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

    async def registry(
        self,
        item_ids: list[str] | None = None,
        date_from = None,
        date_to = None,
        session_id: str | None = None,
        category: str | None = None,
        brand: str | None = None,
        state: str | None = None,
        store: str | None = None,
        channel: str | None = None,
        sort_by: str = "accuracy",
        order: str = "asc",
        page: int = 1,
        page_size: int = 50,
        horizon: str | None = None,
    ) -> dict:
        import random
        random.seed(42)
        op_data = await self.operational_metrics(
            item_ids=item_ids,
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

        registry_items = []
        for item in op_data["items"]:
            vol = item["actual_total"]
            if vol > 5000:
                seg = "A"
            elif vol > 1000:
                seg = "B"
            else:
                seg = "C"
                
            acc = item["accuracy"]
            if acc is None:
                status = "Review"
            elif acc > 80:
                status = "Approved"
            elif acc > 50:
                status = "Review"
            else:
                status = "At Risk"
                
            registry_items.append({
                "id": item["item_id"],
                "sku": item["item_id"],
                "name": item["item_id"],
                "category": category or "Category",
                "segment": seg,
                "status": status,
                "accuracy": item["accuracy"],
                "bias": item["bias"],
                "volume": item["actual_total"],
                "confidence": random.randint(40, 95),
                "trend": random.randint(-15, 20),
                "agents": ["A1", "A2"] if random.random() > 0.5 else ["A1"]
            })
            
        return {
            "items": registry_items,
            "total": op_data["total"],
            "page": op_data["page"],
            "page_size": op_data["page_size"]
        }

    async def segmentation(
        self,
        item_ids: list[str] | None = None,
        date_from = None,
        date_to = None,
        session_id: str | None = None,
        category: str | None = None,
        brand: str | None = None,
        state: str | None = None,
        store: str | None = None,
        channel: str | None = None,
        horizon: str | None = None,
    ) -> dict:
        stmt = select(
            Sales.item_id,
            func.sum(Sales.sales).label('total_sales')
        ).where(Sales.company_id == self.company_id)
        
        if category and category != "All":
            stmt = stmt.where(Sales.cat_id == category)
        if store and store != "All":
            stmt = stmt.where(Sales.store_id == store)
        if state and state != "All":
            stmt = stmt.where(Sales.state_id == state)
        
        stmt = stmt.group_by(Sales.item_id).order_by(text('total_sales DESC'))
        
        rows = (await self.db.execute(stmt)).all()
        
        total_vol = sum((r.total_sales or 0) for r in rows)
        if total_vol == 0:
            total_vol = 1
            
        a_vol, b_vol, c_vol = 0, 0, 0
        a_count, b_count, c_count = 0, 0, 0
        
        cum_vol = 0
        for r in rows:
            v = r.total_sales or 0
            cum_vol += v
            pct = cum_vol / total_vol
            if pct <= 0.8:
                a_vol += v
                a_count += 1
            elif pct <= 0.95:
                b_vol += v
                b_count += 1
            else:
                c_vol += v
                c_count += 1
                
        return {
            "segments": [
                {
                    "segment": "A",
                    "products": a_count,
                    "volume": a_vol,
                    "pctTotal": (a_vol / total_vol) * 100
                },
                {
                    "segment": "B",
                    "products": b_count,
                    "volume": b_vol,
                    "pctTotal": (b_vol / total_vol) * 100
                },
                {
                    "segment": "C",
                    "products": c_count,
                    "volume": c_vol,
                    "pctTotal": (c_vol / total_vol) * 100
                }
            ],
            "volatility": {
                "easy": a_count,
                "challenging": c_count,
                "avgCv": 0.45,
                "highVolPct": 12.5
            },
            "pareto": {
                "top20Products": max(1, int(len(rows) * 0.2)),
                "top20Contribution": (a_vol / total_vol) * 100 if total_vol > 0 else 0
            }
        }
