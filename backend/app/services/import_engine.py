"""Service for orchestrating final data import workflows."""

import os
import logging
import math
import pandas as pd
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, insert
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.upload import UploadProgress
from app.models import SourceConfig, DataUpload, Lookup, Calendar, SellPrice, Sales, Actual
from app.schemas.upload import FileType
from app.services.file_parser import FileParser
from app.services.upload_service import UploadService
from app.schemas.importing import LOOKUP_COLUMNS, CALENDAR_COLUMNS, SELL_PRICES_COLUMNS, SALES_COLUMNS

logger = logging.getLogger(__name__)

STATE_TRANSITIONS = {
    "pending": ["uploading", "cancelled"],
    "uploading": ["parsing", "failed", "cancelled"],
    "parsing": ["validating", "failed", "cancelled"],
    "validating": ["previewing", "awaiting_confirm", "failed", "cancelled"],
    "previewing": ["mapping", "failed", "cancelled"],
    "mapping": ["awaiting_confirm", "failed", "cancelled"],
    "awaiting_confirm": ["confirmed", "cancelled"],
    "confirmed": ["importing", "cancelled"],
    "importing": ["completed", "failed"],
    "failed": [],
    "completed": [],
    "cancelled": []
}


def safe_int(val):
    if val is None or val == "" or (isinstance(val, float) and (math.isnan(val) or val != val)) or pd.isna(val):
        return None
    s = str(val).strip()
    if s.lower() in ("nan", "null", "none"):
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def safe_float(val):
    if val is None or val == "" or (isinstance(val, float) and (math.isnan(val) or val != val)) or pd.isna(val):
        return None
    s = str(val).strip()
    if s.lower() in ("nan", "null", "none"):
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def safe_date(val):
    if val is None or val == "" or (isinstance(val, float) and (math.isnan(val) or val != val)) or pd.isna(val):
        return None
    s = str(val).strip()
    if s.lower() in ("nan", "null", "none"):
        return None
    try:
        return pd.to_datetime(s).date()
    except Exception:
        return None


def safe_str(val):
    if val is None or val == "" or (isinstance(val, float) and (math.isnan(val) or val != val)) or pd.isna(val):
        return None
    s = str(val).strip()
    if s.lower() in ("nan", "null", "none"):
        return None
    return s



def validate_state_transition(current_state: str, new_state: str) -> bool:
    """Validate whether transitioning from current_state to new_state is allowed."""
    allowed = STATE_TRANSITIONS.get(current_state, [])
    return new_state in allowed


class ImportEngine:
    """Import engine orchestrating column mapping application and batch DB loading."""

    def __init__(self, db: AsyncSession, company_id: str):
        """
        Initialize ImportEngine.

        Args:
            db: Database session
            company_id: Company context identifier
        """
        self.db = db
        self.company_id = company_id
        self.file_parser = FileParser()

    async def execute_import(self, upload_id: str, user_id: str) -> None:
        """
        Retrieve validated data from staged file, apply mappings, and load into target tables.

        Args:
            upload_id: Unique upload identifier
            user_id: ID of user triggering import
        """
        result = await self.db.execute(
            select(UploadProgress).where(
                UploadProgress.id == upload_id,
                UploadProgress.company_id == self.company_id
            )
        )
        upload = result.scalar_one_or_none()
        if not upload:
            raise ValueError(f"Upload {upload_id} not found")

        # Validate state transition to importing
        # Note: A `failed` upload must be allowed to retry (e.g. celery retry
        # after a transient IntegrityError). Only block when the upload has
        # already reached a successful terminal state or was cancelled.
        if upload.status in ["completed", "cancelled"]:
            raise ValueError(f"Upload {upload_id} is already in terminal status {upload.status}")
        if upload.status == "failed":
            # Reset to importing so a retry can proceed.
            logger.info(f"Retrying import for previously-failed upload {upload_id}")

        logger.info(f"Transitioning upload {upload_id} to importing state")
        upload.status = "importing"
        upload.current_stage = "importing"
        upload.progress_percentage = 91
        upload.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.commit()

        # Load mapping setup
        meta = upload.meta_info or {}
        mapping_meta = meta.get("mapping_data", {})
        mapping = mapping_meta.get("confirmed_mapping") or mapping_meta.get("suggested_mapping") or {}
        source_type = meta.get("source_type", "transaction")
        
        # Staged file path
        staged_file_path = meta.get("staged_file_path")
        if not staged_file_path or not os.path.exists(staged_file_path):
            raise FileNotFoundError(f"Staged file path not found: {staged_file_path}")

        try:
            # Invert mapping: user_col -> canonical
            # Database models expect: canonical -> user_col
            inverted_mapping = {
                canon: user_col for user_col, canon in mapping.items()
                if canon not in ("__ignore__", "__keep__")
            }

            file_type = upload.file_type or "csv"
            total_imported = 0

            import uuid

            # Execute import according to type
            if source_type == "calendar":
                # Clean calendar table first
                logger.info(f"Replacing Calendar records for company {self.company_id}")
                await self.db.execute(delete(Calendar).where(Calendar.company_id == self.company_id))

                for chunk in self.file_parser.stream_file(staged_file_path, FileType(file_type)):
                    batch = []
                    for row in chunk.data:
                        entry = {}
                        for col in CALENDAR_COLUMNS:
                            user_col = inverted_mapping.get(col)
                            if user_col and user_col in row:
                                entry[col] = row[user_col]

                        batch.append({
                            "id": str(uuid.uuid4()),
                            "company_id": self.company_id,
                            "created_at": datetime.now(timezone.utc),
                            "date": safe_date(entry.get("date")),
                            "wm_yr_wk": safe_int(entry.get("wm_yr_wk")),
                            "weekday": safe_str(entry.get("weekday")),
                            "wday": safe_int(entry.get("wday")),
                            "month": safe_int(entry.get("month")),
                            "year": safe_int(entry.get("year")),
                            "d": safe_str(entry.get("d")),
                            "event_name_1": safe_str(entry.get("event_name_1")),
                            "event_type_1": safe_str(entry.get("event_type_1")),
                            "event_name_2": safe_str(entry.get("event_name_2")),
                            "event_type_2": safe_str(entry.get("event_type_2")),
                            "snap_CA": safe_int(entry.get("snap_CA")) or 0,
                            "snap_TX": safe_int(entry.get("snap_TX")) or 0,
                            "snap_WI": safe_int(entry.get("snap_WI")) or 0
                        })

                    if batch:
                        # Chunk the batch to avoid asyncpg's 32767 parameter limit (17 parameters per row)
                        # 32767 // 17 = 1927 rows max. We use 1000 to be safe.
                        sub_batch_size = 1000
                        for i in range(0, len(batch), sub_batch_size):
                            sub_batch = batch[i:i + sub_batch_size]
                            stmt = pg_insert(Calendar).values(sub_batch)
                            stmt = stmt.on_conflict_do_update(
                                index_elements=["company_id", "d"],
                                set_={
                                    "date": stmt.excluded.date,
                                    "wm_yr_wk": stmt.excluded.wm_yr_wk,
                                    "weekday": stmt.excluded.weekday,
                                    "wday": stmt.excluded.wday,
                                    "month": stmt.excluded.month,
                                    "year": stmt.excluded.year,
                                    "event_name_1": stmt.excluded.event_name_1,
                                    "event_type_1": stmt.excluded.event_type_1,
                                    "event_name_2": stmt.excluded.event_name_2,
                                    "event_type_2": stmt.excluded.event_type_2,
                                    "snap_CA": stmt.excluded.snap_CA,
                                    "snap_TX": stmt.excluded.snap_TX,
                                    "snap_WI": stmt.excluded.snap_WI,
                                },
                            )
                            await self.db.execute(stmt)
                    total_imported += len(batch)
                    
                    # Increment progress ratio
                    progress_fraction = chunk.chunk_index / chunk.total_chunks
                    progress_val = int(91 + progress_fraction * 8)
                    upload.progress_percentage = min(progress_val, 99)
                    upload.processed_rows = total_imported
                    await self.db.flush()
                    await self.db.commit()

            elif source_type in ("sell_prices", "sell_price"):
                # Clean sell_prices table first
                logger.info(f"Replacing SellPrice records for company {self.company_id}")
                await self.db.execute(delete(SellPrice).where(SellPrice.company_id == self.company_id))

                for chunk in self.file_parser.stream_file(staged_file_path, FileType(file_type)):
                    batch = []
                    for row in chunk.data:
                        entry = {}
                        for col in SELL_PRICES_COLUMNS:
                            user_col = inverted_mapping.get(col)
                            if user_col and user_col in row:
                                entry[col] = row[user_col]

                        batch.append({
                            "id": str(uuid.uuid4()),
                            "company_id": self.company_id,
                            "created_at": datetime.now(timezone.utc),
                            "updated_at": datetime.now(timezone.utc),
                            "store_id": safe_str(entry.get("store_id")),
                            "item_id": safe_str(entry.get("item_id")),
                            "wm_yr_wk": safe_int(entry.get("wm_yr_wk")),
                            "sell_price": safe_float(entry.get("sell_price"))
                        })

                    if batch:
                        await self.db.execute(insert(SellPrice), batch)
                    total_imported += len(batch)
                    
                    # Increment progress ratio
                    progress_fraction = chunk.chunk_index / chunk.total_chunks
                    progress_val = int(91 + progress_fraction * 8)
                    upload.progress_percentage = min(progress_val, 99)
                    upload.processed_rows = total_imported
                    await self.db.flush()
                    await self.db.commit()

            elif source_type == "sales":
                # Clean sales table first
                logger.info(f"Replacing Sales records for company {self.company_id}")
                await self.db.execute(delete(Sales).where(Sales.company_id == self.company_id))
                await self.db.commit()

                # Get the underlying asyncpg connection for binary COPY
                conn = await self.db.connection()
                raw_conn = await conn.get_raw_connection()
                driver_conn = raw_conn.dbapi_connection._connection

                columns = [
                    "id", "company_id", "created_at", "item_id", 
                    "dept_id", "cat_id", "store_id", "state_id", "d", "sales", "item_store_id"
                ]

                # Pre-calculate inverted mapping lookup to optimize Python loop speed
                col_to_user_col = {}
                for col in SALES_COLUMNS:
                    user_col = inverted_mapping.get(col)
                    if user_col:
                        col_to_user_col[col] = user_col

                for chunk in self.file_parser.stream_file(staged_file_path, FileType(file_type)):
                    batch_tuples = []
                    now = datetime.now(timezone.utc)
                    for row in chunk.data:
                        item_id = safe_str(row.get(col_to_user_col.get("item_id")))
                        dept_id = safe_str(row.get(col_to_user_col.get("dept_id")))
                        cat_id = safe_str(row.get(col_to_user_col.get("cat_id")))
                        store_id = safe_str(row.get(col_to_user_col.get("store_id")))
                        state_id = safe_str(row.get(col_to_user_col.get("state_id")))
                        d = safe_str(row.get(col_to_user_col.get("d")))
                        sales_val = safe_int(row.get(col_to_user_col.get("sales")))
                        item_store_id = safe_str(row.get(col_to_user_col.get("item_store_id")))

                        batch_tuples.append((
                            str(uuid.uuid4()),
                            self.company_id,
                            now,
                            item_id,
                            dept_id,
                            cat_id,
                            store_id,
                            state_id,
                            d,
                            sales_val,
                            item_store_id
                        ))

                    if batch_tuples:
                        await driver_conn.copy_records_to_table(
                            "sales",
                            records=batch_tuples,
                            columns=columns
                        )
                    total_imported += len(batch_tuples)
                    
                    # Increment progress ratio
                    progress_fraction = chunk.chunk_index / chunk.total_chunks
                    progress_val = int(91 + progress_fraction * 8)
                    
                    # Update progress directly in DB to bypass SQLAlchemy overhead
                    await driver_conn.execute(
                        """
                        UPDATE upload_progress 
                        SET progress_percentage = $1, processed_rows = $2, updated_at = $3
                        WHERE id = $4;
                        """,
                        min(progress_val, 99),
                        total_imported,
                        now,
                        upload_id
                    )

            elif source_type == "lookup":
                # For lookup data: accumulate and replace lookup values
                all_raw_rows = []
                for chunk in self.file_parser.stream_file(staged_file_path, FileType(file_type)):
                    all_raw_rows.extend(chunk.data)
                
                # Replace lookup (fresh master per import)
                logger.info(f"Replacing Lookup records for company {self.company_id}")
                await self.db.execute(delete(Lookup).where(Lookup.company_id == self.company_id))
                
                mapped_entries = []
                for row in all_raw_rows:
                    entry = {}
                    # Canonical LOOKUP columns mapped via standard targets
                    for c in LOOKUP_COLUMNS:
                        user_col = inverted_mapping.get(c)
                        if user_col and user_col in row:
                            val = row[user_col]
                            if isinstance(val, float) and (math.isnan(val) or val != val):
                                val = None
                            elif pd.isna(val):
                                val = None
                            entry[c] = val
                    # Columns the user marked "Keep Original" - preserved under source key
                    for user_col, target in mapping.items():
                        if target == "__keep__" and user_col in row and user_col not in entry:
                            val = row[user_col]
                            if isinstance(val, float) and (math.isnan(val) or val != val):
                                val = None
                            elif pd.isna(val):
                                val = None
                            entry[user_col] = val
                    if entry.get("item_id") and entry.get("store_id"):
                        mapped_entries.append(Lookup(company_id=self.company_id, **entry))
                        
                for entry_model in mapped_entries:
                    self.db.add(entry_model)
                total_imported = len(mapped_entries)
                upload.processed_rows = total_imported
                upload.progress_percentage = 98
                await self.db.flush()

            elif source_type == "actuals":
                session_id = meta.get("session_id")
                if not session_id:
                    raise ValueError("session_id is required for importing actuals")

                item_id_col = inverted_mapping.get("item_id")
                date_col = inverted_mapping.get("date")
                actual_val_col = inverted_mapping.get("actual_quantity") or inverted_mapping.get("actual_value")

                if not item_id_col or not date_col or not actual_val_col:
                    raise ValueError("actuals import requires mappings for item_id, date, and actual_value")

                import uuid
                
                logger.info(f"Replacing Actuals records for session {session_id} and company {self.company_id}")
                await self.db.execute(
                    delete(Actual).where(
                        Actual.company_id == self.company_id,
                        Actual.session_id == session_id
                    )
                )

                for chunk in self.file_parser.stream_file(staged_file_path, FileType(file_type)):
                    batch = []
                    for row in chunk.data:
                        raw_item_id = row.get(item_id_col)
                        raw_date = row.get(date_col)
                        raw_val = row.get(actual_val_col)
                        
                        if not raw_item_id or not raw_date or raw_val is None:
                            continue
                            
                        d = safe_date(raw_date)
                        v = safe_float(raw_val)
                        if not d or v is None:
                            continue

                        batch.append({
                            "id": uuid.uuid4().hex,
                            "session_id": session_id,
                            "company_id": self.company_id,
                            "item_id": safe_str(raw_item_id),
                            "date": d,
                            "actual_value": v
                        })

                    if batch:
                        await self.db.execute(insert(Actual), batch)
                    total_imported += len(batch)

                    progress_fraction = chunk.chunk_index / chunk.total_chunks
                    progress_val = int(91 + progress_fraction * 8)
                    upload.progress_percentage = min(progress_val, 99)
                    upload.processed_rows = total_imported
                    await self.db.flush()
                    await self.db.commit()

            else:
                # For transaction/sales data: stream in chunks and create DataUpload batch records
                for chunk in self.file_parser.stream_file(staged_file_path, FileType(file_type)):
                    mapped_chunk = []
                    for row in chunk.data:
                        # Build the row by walking each source column and applying
                        # the mapping decision for that column.
                        mapped_row = {}
                        for user_col, val in row.items():
                            target = mapping.get(user_col)
                            if target == "__ignore__":
                                # Skip - column is excluded from the row entirely
                                continue
                            
                            # Clean float NaN values to None
                            if isinstance(val, float) and (math.isnan(val) or val != val):
                                val = None
                            elif pd.isna(val):
                                val = None

                            if target == "__keep__":
                                # Preserve under original column name
                                mapped_row[user_col] = val
                            elif target:
                                # Map to canonical field name
                                mapped_row[target] = val
                            else:
                                # No mapping for this source column - drop it
                                # (defensive: don't leak unmapped fields into DB)
                                continue

                        # Derive revenue if absent
                        if not mapped_row.get("revenue") and mapped_row.get("price") and mapped_row.get("quantity"):
                            try:
                                mapped_row["revenue"] = float(mapped_row["price"]) * float(mapped_row["quantity"])
                            except (TypeError, ValueError):
                                pass
                        mapped_chunk.append(mapped_row)

                    if mapped_chunk:
                        batch_record = DataUpload(
                            company_id=self.company_id,
                            source_config_id=upload.source_config_id,
                            upload_date=datetime.now(timezone.utc).isoformat(),
                            row_count=len(mapped_chunk),
                            data=mapped_chunk
                        )
                        self.db.add(batch_record)
                        total_imported += len(mapped_chunk)

                        # Increment progress ratio
                        progress_fraction = chunk.chunk_index / chunk.total_chunks
                        progress_val = int(91 + progress_fraction * 8) # 91-99%
                        upload.progress_percentage = min(progress_val, 99)
                        upload.processed_rows = total_imported
                        await self.db.flush()
                        await self.db.commit()

            # Record transition end timestamp
            upload_service = UploadService(self.db, self.company_id, user_id)
            upload_service._update_stage_timestamp(upload, "importing", "end")

            # Finalize progress
            upload.status = "completed"
            upload.current_stage = "completed"
            upload.progress_percentage = 100
            upload.completed_at = datetime.now(timezone.utc)
            upload.updated_at = datetime.now(timezone.utc)
            await self.db.flush()

            # Create history record
            await upload_service._create_upload_history(upload)

            # Preserve staging file for audit logging
            if os.path.exists(staged_file_path):
                logger.info(f"Preserving staging file for audit logs: {staged_file_path}")

            await self.db.commit()
            logger.info(f"Import process completed successfully for upload {upload_id}. Rows: {total_imported}")

        except Exception as e:
            logger.error(f"Import process failed for upload {upload_id}: {str(e)}")
            await self.db.rollback()
            
            # Reset status to failed
            try:
                result = await self.db.execute(
                    select(UploadProgress).where(UploadProgress.id == upload_id)
                )
                upload_fail = result.scalar_one_or_none()
                if upload_fail:
                    upload_fail.status = "failed"
                    upload_fail.error_message = f"Import error: {str(e)}"[:2000]
                    upload_fail.completed_at = datetime.now(timezone.utc)
                    upload_fail.updated_at = datetime.now(timezone.utc)
                    await self.db.commit()
                    
                    # Create failed history record
                    upload_service = UploadService(self.db, self.company_id, user_id)
                    await upload_service._create_upload_history(upload_fail)
            except Exception as db_err:
                logger.error(f"Failed to update failed status in database: {str(db_err)}")
                
            raise
    
    async def cancel_import(self, upload_id: str, user_id: str) -> None:
        """Cancel import process and perform cleanup of staging file."""
        result = await self.db.execute(
            select(UploadProgress).where(
                UploadProgress.id == upload_id,
                UploadProgress.company_id == self.company_id
            )
        )
        upload = result.scalar_one_or_none()
        if not upload:
            raise ValueError(f"Upload {upload_id} not found")
            
        if upload.status in ["completed", "failed", "cancelled"]:
            return

        upload.status = "cancelled"
        upload.current_stage = "cancelled"
        upload.completed_at = datetime.now(timezone.utc)
        upload.updated_at = datetime.now(timezone.utc)
        
        # Cleanup staged file path
        meta = upload.meta_info or {}
        staged_file_path = meta.get("staged_file_path")
        if staged_file_path and os.path.exists(staged_file_path):
            try:
                os.remove(staged_file_path)
            except Exception as e:
                logger.warning(f"Failed to delete file on cancel: {str(e)}")

        await self.db.flush()
        upload_service = UploadService(self.db, self.company_id, user_id)
        await upload_service._create_upload_history(upload)
        await self.db.commit()
        logger.info(f"Upload {upload_id} successfully cancelled by user.")
