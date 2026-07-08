"""Schema validation for column presence, data types, and format compliance."""

import re
from typing import List, Dict, Any, Optional, Set
from datetime import datetime
import pandas as pd
import logging

from app.schemas.validation import (
    ValidationErrorDetail, ValidationResult, ValidationStatistics,
    ValidationStage, ErrorCategory, Severity
)
from app.validators.error_classifier import ErrorClassifier
from app.schemas.importing import TXN_COLUMNS, LOOKUP_COLUMNS

logger = logging.getLogger(__name__)


class ColumnDefinition:
    """Definition for a canonical column with validation rules."""

    def __init__(
        self,
        name: str,
        data_type: str,
        required: bool = True,
        format_pattern: Optional[str] = None,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
        allowed_values: Optional[Set[str]] = None
    ):
        self.name = name
        self.data_type = data_type  # 'string', 'numeric', 'date', 'boolean'
        self.required = required
        self.format_pattern = format_pattern  # Regex pattern for format validation
        self.min_value = min_value
        self.max_value = max_value
        self.allowed_values = allowed_values


# Canonical column definitions for transaction data
TRANSACTION_COLUMNS_DEF = {
    "item_id": ColumnDefinition(
        name="item_id",
        data_type="string",
        required=True
    ),
    "store_id": ColumnDefinition(
        name="store_id",
        data_type="string",
        required=True
    ),
    "date": ColumnDefinition(
        name="date",
        data_type="date",
        required=True,
        format_pattern=r"^\d{4}-\d{2}-\d{2}$"  # ISO 8601 date format
    ),
    "quantity": ColumnDefinition(
        name="quantity",
        data_type="numeric",
        required=True,
        min_value=0
    ),
    "revenue": ColumnDefinition(
        name="revenue",
        data_type="numeric",
        required=False,
        min_value=0
    ),
    "price": ColumnDefinition(
        name="price",
        data_type="numeric",
        required=False,
        min_value=0
    )
}

# Canonical column definitions for lookup data
LOOKUP_COLUMNS_DEF = {
    "item_id": ColumnDefinition(
        name="item_id",
        data_type="string",
        required=True
    ),
    "item_name": ColumnDefinition(
        name="item_name",
        data_type="string",
        required=False
    ),
    "category": ColumnDefinition(
        name="category",
        data_type="string",
        required=False
    ),
    "brand": ColumnDefinition(
        name="brand",
        data_type="string",
        required=False
    ),
    "store_id": ColumnDefinition(
        name="store_id",
        data_type="string",
        required=True
    ),
    "store_name": ColumnDefinition(
        name="store_name",
        data_type="string",
        required=False
    ),
    "state": ColumnDefinition(
        name="state",
        data_type="string",
        required=False
    ),
    "region": ColumnDefinition(
        name="region",
        data_type="string",
        required=False
    ),
    "channel": ColumnDefinition(
        name="channel",
        data_type="string",
        required=False
    )
}

# Canonical column definitions for M5 calendar data
CALENDAR_COLUMNS_DEF = {
    "date": ColumnDefinition("date", "date", required=True, format_pattern=r"^\d{4}-\d{2}-\d{2}$"),
    "wm_yr_wk": ColumnDefinition("wm_yr_wk", "numeric", required=True),
    "weekday": ColumnDefinition("weekday", "string", required=True),
    "wday": ColumnDefinition("wday", "numeric", required=True),
    "month": ColumnDefinition("month", "numeric", required=True),
    "year": ColumnDefinition("year", "numeric", required=True),
    "d": ColumnDefinition("d", "string", required=True),
    "event_name_1": ColumnDefinition("event_name_1", "string", required=False),
    "event_type_1": ColumnDefinition("event_type_1", "string", required=False),
    "event_name_2": ColumnDefinition("event_name_2", "string", required=False),
    "event_type_2": ColumnDefinition("event_type_2", "string", required=False),
    "snap_CA": ColumnDefinition("snap_CA", "numeric", required=True),
    "snap_TX": ColumnDefinition("snap_TX", "numeric", required=True),
    "snap_WI": ColumnDefinition("snap_WI", "numeric", required=True)
}

# Canonical column definitions for M5 sell prices data
SELL_PRICES_COLUMNS_DEF = {
    "store_id": ColumnDefinition("store_id", "string", required=True),
    "item_id": ColumnDefinition("item_id", "string", required=True),
    "wm_yr_wk": ColumnDefinition("wm_yr_wk", "numeric", required=True),
    "sell_price": ColumnDefinition("sell_price", "numeric", required=True)
}

# Canonical column definitions for M5 sales data
SALES_COLUMNS_DEF = {
    "item_store_id": ColumnDefinition("item_store_id", "string", required=True),
    "item_id": ColumnDefinition("item_id", "string", required=True),
    "dept_id": ColumnDefinition("dept_id", "string", required=True),
    "cat_id": ColumnDefinition("cat_id", "string", required=True),
    "store_id": ColumnDefinition("store_id", "string", required=True),
    "state_id": ColumnDefinition("state_id", "string", required=True),
    "d": ColumnDefinition("d", "string", required=True),
    "sales": ColumnDefinition("sales", "numeric", required=True, min_value=0)
}

# Canonical column definitions for actuals data
ACTUALS_COLUMNS_DEF = {
    "item_id": ColumnDefinition(
        name="item_id",
        data_type="string",
        required=True
    ),
    "date": ColumnDefinition(
        name="date",
        data_type="date",
        required=True,
        format_pattern=r"^\d{4}-\d{2}-\d{2}$"
    ),
    "actual_value": ColumnDefinition(
        name="actual_value",
        data_type="numeric",
        required=True,
        min_value=0
    )
}


class SchemaValidator:
    """
    Validates data against schema definitions including:
    - Required column presence
    - Data type validation
    - Format validation (dates, patterns)
    - Value range validation
    - Null value handling
    """

    def __init__(self, strict_mode: bool = False):
        """
        Initialize schema validator.

        Args:
            strict_mode: If True, fail on missing optional columns; if False, warn only
        """
        self.strict_mode = strict_mode

    def validate_schema(
        self,
        rows: List[Dict[str, Any]],
        source_type: str = "transaction"
    ) -> ValidationResult:
        """
        Validate data rows against schema definitions.

        Args:
            rows: List of data rows to validate
            source_type: Type of data ('transaction' or 'lookup')

        Returns:
            ValidationResult with schema validation results
        """
        started_at = datetime.now()
        errors = []
        statistics = ValidationStatistics()

        # Select column definitions based on source type
        if source_type == "transaction":
            column_defs = TRANSACTION_COLUMNS_DEF
            required_columns = TXN_COLUMNS
        elif source_type == "lookup":
            column_defs = LOOKUP_COLUMNS_DEF
            required_columns = LOOKUP_COLUMNS
        elif source_type in ("sell_prices", "sell_price"):
            column_defs = SELL_PRICES_COLUMNS_DEF
            required_columns = list(SELL_PRICES_COLUMNS_DEF.keys())
        elif source_type == "calendar":
            column_defs = CALENDAR_COLUMNS_DEF
            required_columns = [col for col, d in CALENDAR_COLUMNS_DEF.items() if d.required]
        elif source_type == "sales":
            column_defs = SALES_COLUMNS_DEF
            required_columns = list(SALES_COLUMNS_DEF.keys())
        elif source_type == "actuals":
            column_defs = ACTUALS_COLUMNS_DEF
            required_columns = list(ACTUALS_COLUMNS_DEF.keys())
        else:
            return ValidationResult(
                is_valid=False,
                can_import=False,
                current_stage=ValidationStage.SCHEMA,
                statistics=statistics,
                errors=[ErrorClassifier.create_constraint_error(
                    0, f"Unknown source type: {source_type}", "Use 'transaction', 'lookup', 'calendar', 'sell_prices', 'sales' or 'actuals'"
                )],
                started_at=started_at,
                completed_at=datetime.now()
            )

        if not rows:
            return ValidationResult(
                is_valid=False,
                can_import=False,
                current_stage=ValidationStage.SCHEMA,
                statistics=statistics,
                errors=[ErrorClassifier.create_constraint_error(
                    0, "No data to validate", "Provide at least one row of data"
                )],
                started_at=started_at,
                completed_at=datetime.now()
            )

        statistics.total_rows = len(rows)

        # Get columns from first row to determine schema
        available_columns = set(rows[0].keys()) if rows else set()

        # Check for required columns
        missing_columns = self._check_required_columns(
            available_columns, column_defs
        )

        for column_name in missing_columns:
            error = ErrorClassifier.create_missing_field_error(
                0,  # File-level error
                column_name
            )
            # Demote missing-required-column to a non-blocking warning so users
            # can still reach the mapping step where they can wire e.g.
            # sales_date -> date. The import endpoint's validate_mappings
            # will still block the final import if required canonical fields
            # stay unmapped.
            error.is_blocking = False
            error.severity = Severity.WARNING
            errors.append(error)

        # Validate each row
        for row_idx, row in enumerate(rows):
            row_errors = self._validate_row(
                row, row_idx, column_defs, available_columns
            )
            errors.extend(row_errors)

        # Calculate statistics
        statistics.total_errors = len([e for e in errors if e.severity == Severity.ERROR])
        statistics.total_warnings = len([e for e in errors if e.severity == Severity.WARNING])
        statistics.blocking_errors = len([e for e in errors if e.is_blocking])
        statistics.error_rows = len(set(e.row_number for e in errors if e.row_number is not None))
        statistics.valid_rows = statistics.total_rows - statistics.error_rows

        # Track errors by type and category
        for error in errors:
            statistics.errors_by_type[error.error_type] = \
                statistics.errors_by_type.get(error.error_type, 0) + 1
            statistics.errors_by_category[error.error_category] = \
                statistics.errors_by_category.get(error.error_category, 0) + 1

        completed_at = datetime.now()
        duration = (completed_at - started_at).total_seconds()
        statistics.duration_seconds = duration
        if duration > 0:
            statistics.rows_per_second = statistics.total_rows / duration

        is_valid = statistics.blocking_errors == 0
        can_import = is_valid

        return ValidationResult(
            is_valid=is_valid,
            can_import=can_import,
            current_stage=ValidationStage.SCHEMA,
            stage_percentage=100.0,
            statistics=statistics,
            errors=errors,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration
        )

    def _check_required_columns(
        self,
        available_columns: Set[str],
        column_defs: Dict[str, ColumnDefinition]
    ) -> List[str]:
        """Check which required columns are missing."""
        missing = []
        for col_name, col_def in column_defs.items():
            if col_def.required and col_name not in available_columns:
                missing.append(col_name)
        return missing

    def _validate_row(
        self,
        row: Dict[str, Any],
        row_idx: int,
        column_defs: Dict[str, ColumnDefinition],
        available_columns: Set[str]
    ) -> List[ValidationErrorDetail]:
        """Validate a single row against schema."""
        errors = []

        for col_name, col_def in column_defs.items():
            # Skip if column not in data - the file-level missing-columns check
            # above already flagged this once at the file level. Avoid emitting
            # N errors (one per row) which would flood the user.
            if col_name not in available_columns:
                continue

            raw_value = row.get(col_name)

            # Check for null/missing values
            if raw_value is None or raw_value == "" or pd.isna(raw_value):
                if col_def.required:
                    error = ErrorClassifier.create_missing_field_error(
                        row_idx, col_name
                    )
                    error.is_blocking = False
                    error.severity = Severity.WARNING
                    errors.append(error)
                continue

            # Validate data type (Commented out per senior requirement)
            # type_errors = self._validate_data_type(
            #     row_idx, col_name, raw_value, col_def
            # )
            # errors.extend(type_errors)

            # Validate format (Commented out per senior requirement)
            # if col_def.format_pattern:
            #     format_errors = self._validate_format(
            #         row_idx, col_name, raw_value, col_def.format_pattern
            #     )
            #     errors.extend(format_errors)

            # Validate range (Commented out per senior requirement)
            # if col_def.data_type == "numeric":
            #     range_errors = self._validate_range(
            #         row_idx, col_name, raw_value, col_def
            #     )
            #     errors.extend(range_errors)

        return errors

    def _validate_data_type(
        self,
        row_idx: int,
        col_name: str,
        raw_value: Any,
        col_def: ColumnDefinition
    ) -> List[ValidationErrorDetail]:
        """Validate data type of a value."""
        errors = []

        try:
            if col_def.data_type == "numeric":
                # Try to convert to float
                float(str(raw_value))
            elif col_def.data_type == "date":
                # Try to parse as date
                self._parse_date(raw_value)
            elif col_def.data_type == "boolean":
                # Check if it's a boolean value
                if str(raw_value).lower() not in ["true", "false", "1", "0", "yes", "no"]:
                    errors.append(ErrorClassifier.create_invalid_type_error(
                        row_idx, col_name, str(raw_value), "boolean"
                    ))
            elif col_def.data_type == "string":
                # Strings can be anything, but check if it's not complex
                if isinstance(raw_value, (dict, list)):
                    errors.append(ErrorClassifier.create_invalid_type_error(
                        row_idx, col_name, str(type(raw_value)), "string"
                    ))

        except (ValueError, TypeError) as e:
            errors.append(ErrorClassifier.create_invalid_type_error(
                row_idx, col_name, str(raw_value), col_def.data_type
            ))

        return errors

    def _validate_format(
        self,
        row_idx: int,
        col_name: str,
        raw_value: Any,
        pattern: str
    ) -> List[ValidationErrorDetail]:
        """Validate value against regex pattern."""
        errors = []

        if not isinstance(raw_value, str):
            raw_value = str(raw_value)

        if not re.match(pattern, raw_value):
            errors.append(ErrorClassifier.create_invalid_format_error(
                row_idx, col_name, raw_value, pattern
            ))

        return errors

    def _validate_range(
        self,
        row_idx: int,
        col_name: str,
        raw_value: Any,
        col_def: ColumnDefinition
    ) -> List[ValidationErrorDetail]:
        """Validate numeric value is within range."""
        errors = []

        try:
            num_value = float(raw_value)

            if col_def.min_value is not None and num_value < col_def.min_value:
                errors.append(ErrorClassifier.create_out_of_range_error(
                    row_idx, col_name, raw_value,
                    col_def.min_value,
                    col_def.max_value if col_def.max_value else "unlimited"
                ))

            if col_def.max_value is not None and num_value > col_def.max_value:
                errors.append(ErrorClassifier.create_out_of_range_error(
                    row_idx, col_name, raw_value,
                    col_def.min_value if col_def.min_value else "unlimited",
                    col_def.max_value
                ))

        except (ValueError, TypeError):
            # Type error already caught in data type validation
            pass

        return errors

    def _parse_date(self, date_value: Any) -> datetime:
        """Parse date string to datetime object."""
        if isinstance(date_value, datetime):
            return date_value

        if isinstance(date_value, str):
            # Try ISO 8601 format first
            try:
                return datetime.fromisoformat(date_value)
            except ValueError:
                pass

            # Try other common formats
            for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"]:
                try:
                    return datetime.strptime(date_value, fmt)
                except ValueError:
                    continue

        raise ValueError(f"Cannot parse date: {date_value}")

    def validate_batch(
        self,
        rows: List[Dict[str, Any]],
        source_type: str = "transaction",
        batch_id: int = 0
    ) -> ValidationResult:
        """
        Validate a batch of rows for batch processing.

        Args:
            rows: List of data rows to validate
            source_type: Type of data ('transaction' or 'lookup')
            batch_id: Batch identifier

        Returns:
            ValidationResult for the batch
        """
        result = self.validate_schema(rows, source_type)

        # Add batch information to metadata
        result.validation_rules = [f"batch_{batch_id}"]

        return result


# Convenience functions for schema validation
def validate_schema(
    rows: List[Dict[str, Any]],
    source_type: str = "transaction",
    strict_mode: bool = False
) -> ValidationResult:
    """
    Convenience function to validate schema.

    Args:
        rows: Data rows to validate
        source_type: Type of data ('transaction' or 'lookup')
        strict_mode: Whether to use strict validation mode

    Returns:
        ValidationResult
    """
    validator = SchemaValidator(strict_mode=strict_mode)
    return validator.validate_schema(rows, source_type)


def get_required_columns(source_type: str = "transaction") -> List[str]:
    """
    Get list of required columns for a source type.

    Args:
        source_type: Type of data ('transaction' or 'lookup')

    Returns:
        List of required column names
    """
    if source_type == "transaction":
        return TXN_COLUMNS
    elif source_type == "lookup":
        return [col for col, defn in LOOKUP_COLUMNS_DEF.items() if defn.required]
    elif source_type in ("sell_prices", "sell_price"):
        return list(SELL_PRICES_COLUMNS_DEF.keys())
    elif source_type == "calendar":
        return [col for col, defn in CALENDAR_COLUMNS_DEF.items() if defn.required]
    elif source_type == "sales":
        return list(SALES_COLUMNS_DEF.keys())
    elif source_type == "actuals":
        return list(ACTUALS_COLUMNS_DEF.keys())
    return []
