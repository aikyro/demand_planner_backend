"""FastAPI endpoints for dataset preview, column mapping, and import confirmation."""

import logging
from typing import Dict
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.core.deps import min_role, CurrentUser
from app.models.upload import UploadProgress
from app.models import SourceConfig
from app.schemas.preview import (
    PreviewResponse, PreviewData, DatasetSummaryResponse, DatasetSummary,
    MappingSuggestionResponse, MappingUpdateIn, MappingUpdateResponse,
    ConfirmImportIn, ConfirmImportResponse
)
from app.services.mapping_service import MappingService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/import", tags=["upload-preview"])


@router.get(
    "/uploads/{upload_id}/preview",
    response_model=PreviewResponse,
    summary="Get dataset row-based preview",
    description="Retrieve first few and last few rows of the uploaded file."
)
async def get_dataset_preview(
    upload_id: str,
    user: CurrentUser = Depends(min_role("planner")),
    db: AsyncSession = Depends(get_db)
):
    """Get sample first and last rows of the uploaded dataset."""
    result = await db.execute(
        select(UploadProgress).where(
            UploadProgress.id == upload_id,
            UploadProgress.company_id == user.company_id
        )
    )
    upload = result.scalar_one_or_none()
    if not upload:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Upload {upload_id} not found"
        )
        
    meta = upload.meta_info or {}
    preview_meta = meta.get("preview_data", {})
    first_rows = preview_meta.get("first_rows", [])
    last_rows = preview_meta.get("last_rows", [])
    
    total_cols = len(first_rows[0].keys()) if first_rows else 0
    
    return PreviewResponse(
        upload_id=upload.id,
        preview_data=PreviewData(first_rows=first_rows, last_rows=last_rows),
        total_rows=upload.total_rows or len(first_rows),
        total_columns=total_cols
    )


@router.get(
    "/uploads/{upload_id}/data-summary",
    response_model=DatasetSummaryResponse,
    summary="Get calculated dataset summary statistics",
    description="Retrieve row/column counts, missing values, duplicates, and inferred data types."
)
async def get_dataset_summary(
    upload_id: str,
    user: CurrentUser = Depends(min_role("planner")),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve detailed dataset statistics computed during validation streaming."""
    result = await db.execute(
        select(UploadProgress).where(
            UploadProgress.id == upload_id,
            UploadProgress.company_id == user.company_id
        )
    )
    upload = result.scalar_one_or_none()
    if not upload:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Upload {upload_id} not found"
        )
        
    meta = upload.meta_info or {}
    summary_meta = meta.get("summary", {})
    if not summary_meta:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Dataset summary statistics not available for upload {upload_id}"
        )
        
    return DatasetSummaryResponse(
        upload_id=upload.id,
        summary=DatasetSummary(**summary_meta)
    )


@router.get(
    "/uploads/{upload_id}/mapping/suggest",
    response_model=MappingSuggestionResponse,
    summary="Suggest automatic column mapping configuration",
    description="Fuzzy matches user column names against target canonical columns."
)
async def suggest_mappings(
    upload_id: str,
    user: CurrentUser = Depends(min_role("planner")),
    db: AsyncSession = Depends(get_db)
):
    """Fuzzy matches source header fields to target schema."""
    result = await db.execute(
        select(UploadProgress).where(
            UploadProgress.id == upload_id,
            UploadProgress.company_id == user.company_id
        )
    )
    upload = result.scalar_one_or_none()
    if not upload:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Upload {upload_id} not found"
        )
        
    meta = upload.meta_info or {}
    mapping_meta = meta.get("mapping_data", {})
    summary_meta = meta.get("summary", {})
    
    suggested = mapping_meta.get("suggested_mapping", {})
    confidence = mapping_meta.get("confidence_scores", {})
    
    # Retrieve all headers in the user upload
    user_cols = list(summary_meta.get("column_types", {}).keys())
    if not user_cols and meta.get("preview_data", {}).get("first_rows"):
        user_cols = list(meta["preview_data"]["first_rows"][0].keys())
        
    source_type = meta.get("source_type", "transaction")
    from app.services.mapping_service import TXN_CANONICAL, LOOKUP_CANONICAL
    canonical_columns = LOOKUP_CANONICAL if source_type == "lookup" else TXN_CANONICAL
    
    # Compute unmapped columns lists
    unmapped_columns = [col for col in user_cols if col not in suggested]
    mapped_canonicals = set(suggested.values())
    unmapped_canonical = [col for col in canonical_columns if col not in mapped_canonicals]
    
    return MappingSuggestionResponse(
        upload_id=upload.id,
        source_columns=user_cols,
        canonical_columns=canonical_columns,
        suggested_mapping=suggested,
        confidence=confidence,
        unmapped_columns=unmapped_columns,
        unmapped_canonical=unmapped_canonical
    )


@router.put(
    "/uploads/{upload_id}/mapping",
    response_model=MappingUpdateResponse,
    summary="Update custom column mapping layout",
    description="Save user-configured column mapping layout."
)
async def update_mappings(
    upload_id: str,
    body: MappingUpdateIn,
    user: CurrentUser = Depends(min_role("planner")),
    db: AsyncSession = Depends(get_db)
):
    """Save user column configuration mappings."""
    result = await db.execute(
        select(UploadProgress).where(
            UploadProgress.id == upload_id,
            UploadProgress.company_id == user.company_id
        )
    )
    upload = result.scalar_one_or_none()
    if not upload:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Upload {upload_id} not found"
        )
        
    import copy
    from sqlalchemy.orm.attributes import flag_modified
    meta = copy.deepcopy(upload.meta_info) if upload.meta_info else {}
    source_type = meta.get("source_type", "transaction")
    
    # Validate the mapping configuration
    validation_res = MappingService.validate_mappings(body.column_mappings, source_type)
    
    # Save the updated configuration
    if "mapping_data" not in meta:
        meta["mapping_data"] = {}
    meta["mapping_data"]["confirmed_mapping"] = body.column_mappings
    upload.meta_info = meta
    flag_modified(upload, "meta_info")
    
    await db.flush()
    await db.commit()
    
    return MappingUpdateResponse(
        upload_id=upload.id,
        status="mapping_saved",
        column_mappings=body.column_mappings,
        validation_result=validation_res
    )


@router.post(
    "/uploads/{upload_id}/confirm",
    response_model=ConfirmImportResponse,
    summary="Confirm column mappings and lock import config",
    description="Locks down column configuration, saves it on SourceConfig, and transitions status."
)
async def confirm_import(
    upload_id: str,
    body: ConfirmImportIn,
    user: CurrentUser = Depends(min_role("planner")),
    db: AsyncSession = Depends(get_db)
):
    """Confirm schema configuration layout and finalize import."""
    result = await db.execute(
        select(UploadProgress).where(
            UploadProgress.id == upload_id,
            UploadProgress.company_id == user.company_id
        )
    )
    upload = result.scalar_one_or_none()
    if not upload:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Upload {upload_id} not found"
        )
        
    import copy
    from sqlalchemy.orm.attributes import flag_modified
    meta = copy.deepcopy(upload.meta_info) if upload.meta_info else {}
    source_type = meta.get("source_type", "transaction")
    
    validation_res = MappingService.validate_mappings(body.column_mappings, source_type)
    if not validation_res.is_valid and not body.proceed_with_warnings:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Mapping validation failed: missing required canonical fields {validation_res.missing_required}"
        )
        
    # Invert mapping: user_col -> canonical_col into canonical_col -> user_col
    inverted_mapping = {
        canon: user_col for user_col, canon in body.column_mappings.items()
        if canon not in ("__ignore__", "__keep__")
    }
    
    # Load associated SourceConfig and save mappings
    if upload.source_config_id:
        cfg_result = await db.execute(
            select(SourceConfig).where(
                SourceConfig.id == upload.source_config_id,
                SourceConfig.company_id == user.company_id
            )
        )
        source_cfg = cfg_result.scalar_one_or_none()
        if source_cfg:
            source_cfg.column_mappings = inverted_mapping
            db.add(source_cfg)
            
    # Transition upload status
    upload.status = "confirmed"
    upload.current_stage = "confirmed"
    if "mapping_data" not in meta:
        meta["mapping_data"] = {}
    meta["mapping_data"]["confirmed_mapping"] = body.column_mappings
    upload.meta_info = meta
    flag_modified(upload, "meta_info")
    
    await db.flush()
    await db.commit()
    
    logger.info(f"Import configuration mapping confirmed for upload {upload_id}")
    
    return ConfirmImportResponse(
        upload_id=upload.id,
        status="confirmed",
        message="Import configuration confirmed. Data ready for processing.",
        estimated_import_time="00:00:10"
    )


@router.post(
    "/uploads/{upload_id}/import",
    response_model=ConfirmImportResponse,
    summary="Confirm column mappings and trigger final database import",
    description="Trigger the Celery background task to load mapped rows into targeted databases."
)
async def import_dataset(
    upload_id: str,
    body: ConfirmImportIn,
    user: CurrentUser = Depends(min_role("planner")),
    db: AsyncSession = Depends(get_db)
):
    """Confirm column mapping layout and trigger final database batch import."""
    result = await db.execute(
        select(UploadProgress).where(
            UploadProgress.id == upload_id,
            UploadProgress.company_id == user.company_id
        )
    )
    upload = result.scalar_one_or_none()
    if not upload:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Upload {upload_id} not found"
        )
        
    import copy
    from sqlalchemy.orm.attributes import flag_modified
    meta = copy.deepcopy(upload.meta_info) if upload.meta_info else {}
    source_type = body.source_type or meta.get("source_type", "transaction")
    meta["source_type"] = source_type
    upload.meta_info = meta
    flag_modified(upload, "meta_info")
    
    validation_res = MappingService.validate_mappings(body.column_mappings, source_type)
    if not validation_res.is_valid and not body.proceed_with_warnings:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Mapping validation failed: missing required canonical fields {validation_res.missing_required}"
        )
        
    # Invert mapping: user_col -> canonical_col into canonical_col -> user_col
    inverted_mapping = {
        canon: user_col for user_col, canon in body.column_mappings.items()
        if canon not in ("__ignore__", "__keep__")
    }
    
    # Load associated SourceConfig and save mappings
    if upload.source_config_id:
        cfg_result = await db.execute(
            select(SourceConfig).where(
                SourceConfig.id == upload.source_config_id,
                SourceConfig.company_id == user.company_id
            )
        )
        source_cfg = cfg_result.scalar_one_or_none()
        if source_cfg:
            source_cfg.column_mappings = inverted_mapping
            db.add(source_cfg)
            
    # Transition upload status to confirmed
    upload.status = "confirmed"
    upload.current_stage = "confirmed"
    if "mapping_data" not in meta:
        meta["mapping_data"] = {}
    meta["mapping_data"]["confirmed_mapping"] = body.column_mappings
    upload.meta_info = meta
    flag_modified(upload, "meta_info")
    
    await db.flush()
    await db.commit()
    
    # Trigger background Celery import task
    from app.tasks.upload_tasks import process_import_task
    process_import_task.delay(
        upload_id=upload.id,
        company_id=user.company_id,
        user_id=user.id
    )
    
    logger.info(f"Import process triggered for upload {upload_id}")
    
    return ConfirmImportResponse(
        upload_id=upload.id,
        status="importing",
        message="Import started. Use progress endpoint to monitor.",
        estimated_import_time="00:00:10"
    )
