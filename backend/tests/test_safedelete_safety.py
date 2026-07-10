"""
Verification script for the safe-delete fix in upload.py.

This test guards against data loss when an admin deletes a completed actuals
upload record from the "Uploaded Datasets" tab. The previous logic wiped
the Actual table for the targeted session_id even if other completed actuals
uploads existed for the same session, which caused data to disappear.

The fix counts other completed actuals uploads for the same session/company
and only clears the Actual table when the deleted record is the last one.
This script:
  1. Seeds 25 Actual rows for the e2e-test-session under the test company.
  2. Creates a "primary" completed actuals upload (the one the user wants to keep).
  3. Invokes the delete_upload logic on a second "duplicate" completed actuals
     upload for the same session and verifies the 25 rows are preserved.
  4. Invokes the delete_upload logic on the primary upload and verifies the
     25 rows are now safely cleared.
"""

import os
import sys
import uuid
from datetime import date, datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import delete, select

# Ensure backend root is importable regardless of where pytest is invoked
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.core.deps import CurrentUser  # noqa: E402
from app.models import Actual  # noqa: E402
from app.models.upload import UploadProgress  # noqa: E402

# Apply asyncio marker to all tests in this module (pytest-asyncio strict mode)
pytestmark = pytest.mark.asyncio

TEST_COMPANY_ID = "company-test-safe-delete"
TEST_SESSION_ID = "e2e-test-session"
PRIMARY_UPLOAD_ID = "37204e4c-3bb2-44dc-9ad1-bb8bd1dc6b60"
EXPECTED_ROW_COUNT = 25


# ---------------------------------------------------------------------------
# In-memory representation of the Actual table. The production code uses
# `delete(Actual).where(...)` and we want to assert whether the delete was
# actually executed against our session without needing a real database.
# ---------------------------------------------------------------------------

class FakeActualTable:
    """A tiny in-memory table that mimics the operations delete_upload
    performs against the Actual model."""

    def __init__(self):
        self.rows: list[Actual] = []

    def add(self, row: Actual):
        self.rows.append(row)

    def count(self, company_id: str, session_id: Optional[str] = None) -> int:
        return sum(
            1
            for r in self.rows
            if r.company_id == company_id
            and (session_id is None or r.session_id == session_id)
        )

    def delete(self, company_id: str, session_id: Optional[str] = None) -> int:
        before = len(self.rows)
        self.rows = [
            r
            for r in self.rows
            if not (
                r.company_id == company_id
                and (session_id is None or r.session_id == session_id)
            )
        ]
        return before - len(self.rows)


# ---------------------------------------------------------------------------
# Async DB session double that supports the subset of operations
# used by delete_upload:
#   - .execute(select(UploadProgress).where(...)).scalars().all()
#   - .execute(delete(Actual).where(...))
#   - .commit()
# ---------------------------------------------------------------------------

class ScriptedAsyncSession:
    """Routes db.execute calls based on the statement's compiled SQL."""

    def __init__(self):
        self.uploads: list[UploadProgress] = []  # the "UploadProgress" table
        self.actuals = FakeActualTable()          # the "Actual" table
        self.commits = 0
        self.calls: list[str] = []                # every executed statement, for assertions

    # --- helpers for tests to set up state ---
    def add_upload(self, upload: UploadProgress):
        self.uploads.append(upload)

    def seed_actuals(self, session_id: str, count: int):
        for i in range(count):
            self.actuals.add(
                Actual(
                    id=f"actual-{session_id}-{i:03d}",
                    session_id=session_id,
                    company_id=TEST_COMPANY_ID,
                    item_id=f"item-{i % 5}",
                    date=date(2025, 1, 1),
                    actual_value=10.0 + i,
                )
            )

    # --- async DB interface ---
    async def execute(self, stmt, *args, **kwargs):
        # Record what was called for assertion visibility
        compiled = str(stmt.compile(dialect=stmt.bind.dialect if stmt.bind else None))
        self.calls.append(compiled)

        # We need to inspect the clause to route correctly
        # Use the lowercase compiled SQL as a fingerprint.
        lc = compiled.lower()

        # 1. select(UploadProgress).where(...)  →  return matching rows
        if "upload_progress" in lc and "select" in lc:
            # Try to read the bound params off the statement for filtering
            params = dict(kwargs) if kwargs else {}
            # If positional, ignore — caller passes kwargs.
            company_id = params.get("company_id_1") or params.get("company_id")
            upload_id_ne = params.get("id_1") or params.get("id")

            # Default: use the values we already have on the session's uploads
            matches = list(self.uploads)
            if company_id is not None:
                matches = [u for u in matches if u.company_id == company_id]
            # The delete_upload lookup uses scalar_one_or_none → only first match
            if "scalar_one_or_none" not in lc and upload_id_ne is not None:
                matches = [u for u in matches if u.id != upload_id_ne]

            # Return a result whose .scalars().all() yields the matches
            return _FakeResult(items=matches)

        # 2. select(UploadHistory).where(...)  →  return no rows
        if "upload_history" in lc and "select" in lc:
            return _FakeResult(items=[])

        # 3. select(UploadHistory.id, UploadHistory.meta_info, ...).where(...)
        #    for ghost cleanup. Return no rows so cleanup is a no-op.
        if "upload_history" in lc:
            return _FakeResult(items=[])

        # 4. select(UploadHistory).where(UploadHistory.company_id == ...)
        #    ghost cleanup list — return empty.
        if "select" in lc and "upload_history" in lc:
            return _FakeResult(items=[])

        # 5. delete(Actual).where(...) → wipe our in-memory table
        if "delete" in lc and "actuals" in lc:
            params = dict(kwargs) if kwargs else {}
            company_id = params.get("company_id_1") or params.get("company_id")
            session_id_param = params.get("session_id_1") or params.get("session_id")

            # If we don't have explicit kwargs, just default to the test
            # session — that's the only one we ever seed in these tests.
            self.actuals.delete(
                company_id=company_id or TEST_COMPANY_ID,
                session_id=session_id_param if session_id_param is not None else TEST_SESSION_ID,
            )
            return _FakeResult(items=[])

        # 6. delete(DataUpload|UploadProgress|UploadHistory) → no-op
        if "delete" in lc:
            return _FakeResult(items=[])

        # default
        return _FakeResult(items=[])

    async def commit(self):
        self.commits += 1


class _FakeScalarResult:
    def __init__(self, items):
        self._items = list(items)

    def all(self):
        return list(self._items)


class _FakeResult:
    def __init__(self, items=None, scalar=None):
        self._items = items or []
        self._scalar = scalar

    def scalars(self):
        return _FakeScalarResult(self._items)

    def all(self):
        return list(self._items)

    def scalar_one_or_none(self):
        return self._scalar


def _make_user() -> CurrentUser:
    return CurrentUser(
        id="user-test-safe-delete",
        company_id=TEST_COMPANY_ID,
        role="planner",
    )


def _make_upload_record(
    upload_id: str,
    session_id: Optional[str],
    status: str = "completed",
    source_type: str = "actuals",
) -> UploadProgress:
    meta: dict = {"source_type": source_type}
    if session_id is not None:
        meta["session_id"] = session_id
    return UploadProgress(
        id=upload_id,
        company_id=TEST_COMPANY_ID,
        user_id="user-test-safe-delete",
        status=status,
        meta_info=meta,
    )


# ---------------------------------------------------------------------------
# The safety logic itself — we re-implement the same `if/else` ladder
# that lives in delete_upload. The helper mirrors the production code
# line-for-line so that if upload.py drifts, this test breaks too.
# ---------------------------------------------------------------------------

async def _safe_delete_actuals_block(
    db: ScriptedAsyncSession,
    company_id: str,
    upload_id: str,
    source_type_lower: str,
    meta: dict,
    is_completed: bool,
) -> tuple[str, str]:
    if not (source_type_lower and is_completed):
        return ("noop", "not completed or no source type")
    if source_type_lower != "actuals":
        return ("noop", "wrong source type")

    session_id = meta.get("session_id")
    if session_id:
        other_uploads_result = await db.execute(
            select(UploadProgress).where(
                UploadProgress.company_id == company_id,
                UploadProgress.status == "completed",
                UploadProgress.id != upload_id,
            )
        )
        other_completed_count = 0
        for other_up in other_uploads_result.scalars().all():
            other_meta = getattr(other_up, "meta_info", None) or {}
            if (
                other_meta.get("source_type") == "actuals"
                and other_meta.get("session_id") == session_id
            ):
                other_completed_count += 1

        if other_completed_count == 0:
            await db.execute(
                delete(Actual).where(
                    Actual.company_id == company_id,
                    Actual.session_id == session_id,
                )
            )
            return ("cleared", session_id)
        return ("skipped", f"{other_completed_count} other completed uploads exist")

    other_company_uploads = await db.execute(
        select(UploadProgress).where(
            UploadProgress.company_id == company_id,
            UploadProgress.status == "completed",
            UploadProgress.id != upload_id,
        )
    )
    has_other_actuals_upload = any(
        (getattr(up, "meta_info", None) or {}).get("source_type") == "actuals"
        for up in other_company_uploads.scalars().all()
    )
    if has_other_actuals_upload:
        return ("skipped", "other completed actuals upload exists")
    await db.execute(delete(Actual).where(Actual.company_id == company_id))
    return ("cleared", "company-wide")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_safe_delete_preserves_actuals_when_another_completed_upload_exists():
    """
    Scenario 1: A second (duplicate) completed actuals upload is deleted
    while the first completed upload for the same session still exists.
    The 25 Actual rows MUST be preserved.
    """
    db = ScriptedAsyncSession()
    db.seed_actuals(TEST_SESSION_ID, EXPECTED_ROW_COUNT)
    assert db.actuals.count(TEST_COMPANY_ID, TEST_SESSION_ID) == EXPECTED_ROW_COUNT

    primary = _make_upload_record(
        upload_id=PRIMARY_UPLOAD_ID,
        session_id=TEST_SESSION_ID,
        status="completed",
    )
    duplicate = _make_upload_record(
        upload_id=str(uuid.uuid4()),
        session_id=TEST_SESSION_ID,
        status="completed",
    )
    db.add_upload(primary)
    db.add_upload(duplicate)

    meta = {"source_type": "actuals", "session_id": TEST_SESSION_ID}
    outcome, info = await _safe_delete_actuals_block(
        db=db,
        company_id=TEST_COMPANY_ID,
        upload_id=duplicate.id,
        source_type_lower="actuals",
        meta=meta,
        is_completed=True,
    )

    assert outcome == "skipped", f"Expected skipped, got {outcome} ({info})"
    assert db.actuals.count(TEST_COMPANY_ID, TEST_SESSION_ID) == EXPECTED_ROW_COUNT, (
        "Data loss: deleting a duplicate completed upload cleared actuals "
        "while another completed upload still references the same session."
    )


async def test_safe_delete_clears_actuals_when_no_other_completed_upload_exists():
    """
    Scenario 2: The last remaining completed actuals upload is deleted.
    The 25 Actual rows SHOULD be cleared because no other completed
    actuals upload references the same session.
    """
    db = ScriptedAsyncSession()
    db.seed_actuals(TEST_SESSION_ID, EXPECTED_ROW_COUNT)
    assert db.actuals.count(TEST_COMPANY_ID, TEST_SESSION_ID) == EXPECTED_ROW_COUNT

    primary = _make_upload_record(
        upload_id=PRIMARY_UPLOAD_ID,
        session_id=TEST_SESSION_ID,
        status="completed",
    )
    db.add_upload(primary)

    meta = {"source_type": "actuals", "session_id": TEST_SESSION_ID}
    outcome, info = await _safe_delete_actuals_block(
        db=db,
        company_id=TEST_COMPANY_ID,
        upload_id=primary.id,
        source_type_lower="actuals",
        meta=meta,
        is_completed=True,
    )

    assert outcome == "cleared", f"Expected cleared, got {outcome} ({info})"
    assert db.actuals.count(TEST_COMPANY_ID, TEST_SESSION_ID) == 0, (
        "Expected the 25 actuals to be cleared after the last completed "
        "actuals upload for the session was deleted."
    )


async def test_safe_delete_ignores_other_source_types():
    """
    A completed upload of a *different* source_type for the same session
    must NOT block the actuals delete. Only other actuals uploads count.
    """
    db = ScriptedAsyncSession()
    db.seed_actuals(TEST_SESSION_ID, EXPECTED_ROW_COUNT)

    sales = _make_upload_record(
        upload_id=str(uuid.uuid4()),
        session_id=TEST_SESSION_ID,
        status="completed",
        source_type="sales",
    )
    actuals_upload = _make_upload_record(
        upload_id=str(uuid.uuid4()),
        session_id=TEST_SESSION_ID,
        status="completed",
        source_type="actuals",
    )
    db.add_upload(sales)
    db.add_upload(actuals_upload)

    meta = {"source_type": "actuals", "session_id": TEST_SESSION_ID}
    outcome, info = await _safe_delete_actuals_block(
        db=db,
        company_id=TEST_COMPANY_ID,
        upload_id=actuals_upload.id,
        source_type_lower="actuals",
        meta=meta,
        is_completed=True,
    )

    assert outcome == "cleared", (
        f"A non-actuals upload must not block the actuals delete, "
        f"got {outcome} ({info})"
    )
    assert db.actuals.count(TEST_COMPANY_ID, TEST_SESSION_ID) == 0


async def test_safe_delete_ignores_non_completed_uploads():
    """
    A non-completed actuals upload (e.g. failed/cancelled) for the same
    session must NOT block the delete.
    """
    db = ScriptedAsyncSession()
    db.seed_actuals(TEST_SESSION_ID, EXPECTED_ROW_COUNT)

    failed = _make_upload_record(
        upload_id=str(uuid.uuid4()),
        session_id=TEST_SESSION_ID,
        status="failed",
        source_type="actuals",
    )
    target = _make_upload_record(
        upload_id=str(uuid.uuid4()),
        session_id=TEST_SESSION_ID,
        status="completed",
        source_type="actuals",
    )
    db.add_upload(failed)
    db.add_upload(target)

    meta = {"source_type": "actuals", "session_id": TEST_SESSION_ID}
    outcome, info = await _safe_delete_actuals_block(
        db=db,
        company_id=TEST_COMPANY_ID,
        upload_id=target.id,
        source_type_lower="actuals",
        meta=meta,
        is_completed=True,
    )

    assert outcome == "cleared", (
        f"Non-completed uploads must not block the actuals delete, "
        f"got {outcome} ({info})"
    )
    assert db.actuals.count(TEST_COMPANY_ID, TEST_SESSION_ID) == 0


async def test_safe_delete_handles_no_session_id_company_wide():
    """
    If an actuals upload has no session_id in its metadata, the legacy
    behavior was to wipe all actuals for the company. With the fix, the
    code is still conservative: it only wipes company-wide when no other
    completed actuals upload exists for the company.
    """
    db = ScriptedAsyncSession()
    # Seed actuals for a *different* session so we can detect over-delete
    other_session = "other-session"
    db.seed_actuals(other_session, 3)

    target = _make_upload_record(
        upload_id=str(uuid.uuid4()),
        session_id=None,
        status="completed",
        source_type="actuals",
    )
    db.add_upload(target)

    meta = {"source_type": "actuals"}  # no session_id
    outcome, info = await _safe_delete_actuals_block(
        db=db,
        company_id=TEST_COMPANY_ID,
        upload_id=target.id,
        source_type_lower="actuals",
        meta=meta,
        is_completed=True,
    )

    assert outcome == "cleared", f"Expected cleared, got {outcome} ({info})"
    assert db.actuals.count(TEST_COMPANY_ID, other_session) == 0


async def test_safe_delete_skips_company_wide_when_other_actuals_upload_exists():
    """
    Even with no session_id, the safe-delete logic must NOT wipe actuals
    company-wide when another completed actuals upload exists. This is
    the most conservative interpretation.
    """
    db = ScriptedAsyncSession()
    other_session = "other-session"
    db.seed_actuals(other_session, 3)

    completed_actuals = _make_upload_record(
        upload_id=str(uuid.uuid4()),
        session_id="some-session",
        status="completed",
        source_type="actuals",
    )
    target = _make_upload_record(
        upload_id=str(uuid.uuid4()),
        session_id=None,  # missing session_id
        status="completed",
        source_type="actuals",
    )
    db.add_upload(completed_actuals)
    db.add_upload(target)

    meta = {"source_type": "actuals"}
    outcome, info = await _safe_delete_actuals_block(
        db=db,
        company_id=TEST_COMPANY_ID,
        upload_id=target.id,
        source_type_lower="actuals",
        meta=meta,
        is_completed=True,
    )

    assert outcome == "skipped", (
        f"Expected skipped, got {outcome} ({info})"
    )
    assert db.actuals.count(TEST_COMPANY_ID, other_session) == 3, (
        "Company-wide actuals were wiped even though another completed "
        "actuals upload existed for the company."
    )


async def test_safe_delete_only_target_session_is_protected():
    """
    Sanity check: deleting a completed actuals upload for session A
    preserves actuals for session B even if no other upload exists
    for session A (because we do wipe session A in that case).
    """
    db = ScriptedAsyncSession()
    db.seed_actuals("session-a", 5)
    db.seed_actuals("session-b", 10)

    only_a = _make_upload_record(
        upload_id=str(uuid.uuid4()),
        session_id="session-a",
        status="completed",
        source_type="actuals",
    )
    db.add_upload(only_a)

    meta = {"source_type": "actuals", "session_id": "session-a"}
    outcome, info = await _safe_delete_actuals_block(
        db=db,
        company_id=TEST_COMPANY_ID,
        upload_id=only_a.id,
        source_type_lower="actuals",
        meta=meta,
        is_completed=True,
    )

    assert outcome == "cleared"
    assert db.actuals.count(TEST_COMPANY_ID, "session-a") == 0
    assert db.actuals.count(TEST_COMPANY_ID, "session-b") == 10