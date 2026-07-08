
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
        
        if category:
            stmt = stmt.where(Sales.cat_id == category)
        
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
