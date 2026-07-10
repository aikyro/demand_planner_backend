"""Reusable Redis caching layer for dashboard / operational queries.

Builds on the shared async ``redis_client`` (app.core.redis). Keys are namespaced
per company AND per forecast session so invalidation can be selective:

    dash:{company_id}:{entity}:{session_id|all}:{suffix}

The ``all`` session segment holds cross-session aggregates; any write that
touches one session also stales the ``all`` bucket, so session-scoped
invalidation removes both — but leaves other sessions' entries intact.

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

# Session segment used for entries that aggregate across all sessions.
ALL_SESSIONS = "all"


def cache_key(
    company_id: str,
    entity: str,
    suffix: str | None = None,
    session_id: str | None = None,
) -> str:
    """Build a namespaced cache key scoped to a company and forecast session.

    ``session_id=None`` means the entry aggregates across sessions and lands in
    the ``all`` segment (stale whenever ANY session changes).
    """
    base = f"dash:{company_id}:{entity}:{session_id or ALL_SESSIONS}"
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


async def get_json_with_flag(key: str) -> tuple[Any, bool]:
    """Like get_json(), but also returns whether the key was a cache HIT.

    Returns:
        (None, False) on MISS or poisoned entry.
        (parsed_value, True) on HIT.
    """
    raw = await redis_client.get(key)
    if raw is None:
        return None, False
    try:
        return json.loads(raw), True
    except (ValueError, TypeError):
        # Poisoned entry — drop it so the caller recomputes.
        await redis_client.delete(key)
        return None, False



async def set_json(key: str, value: Any, ttl: int = OPERATIONAL_TTL) -> None:
    """Store ``value`` as JSON under ``key`` with an expiry."""
    await redis_client.setex(key, ttl, json.dumps(value, default=str))


async def _delete_pattern(pattern: str) -> int:
    deleted = 0
    async for key in redis_client.scan_iter(match=pattern, count=500):
        await redis_client.delete(key)
        deleted += 1
    return deleted


async def invalidate_company(company_id: str) -> int:
    """Delete every cached dashboard entry for a company.

    Coarse hammer — prefer :func:`invalidate_session` when the affected
    session is known. Returns the number of keys removed.
    """
    return await _delete_pattern(f"dash:{company_id}:*")


async def invalidate_session(company_id: str, session_id: str | None) -> int:
    """Selectively drop cache entries affected by a write to one session.

    Removes that session's entries plus the cross-session ``all`` bucket
    (aggregates include the changed session), leaving other sessions' caches
    untouched. Falls back to company-wide invalidation when the session is
    unknown. Never flushes Redis globally.
    """
    if not session_id:
        return await invalidate_company(company_id)
    deleted = await _delete_pattern(f"dash:{company_id}:*:{session_id}:*")
    deleted += await _delete_pattern(f"dash:{company_id}:*:{session_id}")
    deleted += await _delete_pattern(f"dash:{company_id}:*:{ALL_SESSIONS}:*")
    deleted += await _delete_pattern(f"dash:{company_id}:*:{ALL_SESSIONS}")
    return deleted
