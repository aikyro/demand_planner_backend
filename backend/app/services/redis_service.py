"""Reusable Redis caching layer for dashboard / operational queries.

Builds on the shared async ``redis_client`` (app.core.redis). Keys are namespaced
per company so a single company's cache can be invalidated wholesale when a new
forecast is published:

    dash:{company_id}:{entity}:{suffix}

TTLs come from settings (short TTL for volatile operational data, longer for
reference/metadata).
"""
import json
from typing import Any

from app.core.redis import redis_client
from app.core.config import settings


# TTL (seconds) for volatile operational/dashboard data.
OPERATIONAL_TTL = settings.DASHBOARD_CACHE_TTL
# TTL (seconds) for slow-changing reference data (filter option lists, etc.).
REFERENCE_TTL = settings.DASHBOARD_REFERENCE_TTL


def cache_key(company_id: str, entity: str, suffix: str | None = None) -> str:
    """Build a namespaced cache key scoped to a company."""
    base = f"dash:{company_id}:{entity}"
    return f"{base}:{suffix}" if suffix else base


async def get_json(key: str) -> Any | None:
    """Return the cached JSON value for ``key`` or ``None`` if absent/corrupt."""
    raw = await redis_client.get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        # Poisoned entry — drop it so the caller recomputes.
        await redis_client.delete(key)
        return None


async def set_json(key: str, value: Any, ttl: int = OPERATIONAL_TTL) -> None:
    """Store ``value`` as JSON under ``key`` with an expiry."""
    await redis_client.setex(key, ttl, json.dumps(value, default=str))


async def invalidate_company(company_id: str) -> int:
    """Delete every cached dashboard entry for a company.

    Called on forecast publish / override approval so dashboards reflect the new
    data on the next request. Returns the number of keys removed.
    """
    pattern = f"dash:{company_id}:*"
    deleted = 0
    async for key in redis_client.scan_iter(match=pattern, count=500):
        await redis_client.delete(key)
        deleted += 1
    return deleted
