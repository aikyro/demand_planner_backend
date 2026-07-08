"""Data quality validation for missing values, duplicates, outliers, and consistency."""

from typing import List, Dict, Any, Optional, Set, Tuple
from datetime import datetime
from collections import defaultdict
import statistics
import logging

from app.schemas.validation import (
    ValidationErrorDetail, ValidationResult, ValidationStatistics,
    ValidationStage, ErrorCategory, Severity
)
from app.validators.error_classifier import ErrorClassifier

logger = logging.getLogger(__name__)


class DataQualityValidator:
    """
    Validates data quality including:
    - Missing value detection by column
    - Duplicate row detection (exact matches)
    - Outlier detection for numeric columns
    - Inconsistent data type detection
    - Encoding validation
    - Data consistency checks
    """

    def __init__(
        self,
        missing_value_threshold: float = 0.5,  # Allow up to 50% missing values
        duplicate_threshold: int = 1,  # More than 1 duplicate is an error
        outlier_std_dev: float = 3.0,  # 3 standard deviations for outlier detection
        key_columns: Optional[List[str]] = None
    ):
        """
        Initialize data quality validator.

        Args:
            missing_value_threshold: Proportion of missing values allowed (0-1)
            duplicate_threshold: Number of duplicates to allow before error
            outlier_std_dev: Standard deviations for outlier detection
            key_columns: Columns to use for duplicate detection (default: product_id, location_id, date)
        """
        self.missing_value_threshold = missing_value_threshold
        self.duplicate_threshold = duplicate_threshold
        self.outlier_std_dev = outlier_std_dev
        self.key_columns = key_columns or ["item_id", "store_id", "date"]

    def validate_data_quality(
        self,
        rows: List[Dict[str, Any]],
        source_type: str = "transaction"
    ) -> ValidationResult:
        """
        Validate data quality metrics.

        Args:
            rows: List of data rows to validate
            source_type: Type of data ('transaction' or 'lookup')

        Returns:
            ValidationResult with data quality validation results
        """
        started_at = datetime.now()
        errors = []
        statistics = ValidationStatistics()

        if not rows:
            return ValidationResult(
                is_valid=False,
                can_import=False,
                current_stage=ValidationStage.DATA_QUALITY,
                statistics=statistics,
                errors=[ErrorClassifier.create_constraint_error(
                    0, "No data to validate", "Provide at least one row of data"
                )],
                started_at=started_at,
                completed_at=datetime.now()
            )

        statistics.total_rows = len(rows)

        # Check for missing values
        missing_errors, missing_counts = self._check_missing_values(rows, source_type)
        errors.extend(missing_errors)
        statistics.missing_values = missing_counts

        # Check for duplicates
        duplicate_errors, duplicate_count = self._check_duplicates(rows)
        errors.extend(duplicate_errors)
        statistics.duplicate_count = duplicate_count

        # Check for outliers (only for numeric columns)
        outlier_errors, outlier_count = self._check_outliers(rows, source_type)
        errors.extend(outlier_errors)
        statistics.outlier_count = outlier_count

        # Check for data consistency
        consistency_errors = self._check_consistency(rows, source_type)
        errors.extend(consistency_errors)

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
            current_stage=ValidationStage.DATA_QUALITY,
            stage_percentage=100.0,
            statistics=statistics,
            errors=errors,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration
        )

    def _check_missing_values(
        self,
        rows: List[Dict[str, Any]],
        source_type: str
    ) -> Tuple[List[ValidationErrorDetail], Dict[str, int]]:
        """Check for missing values by column."""
        errors = []
        missing_counts = defaultdict(int)

        # Get all columns from rows
        all_columns = set()
        for row in rows:
            all_columns.update(row.keys())

        # Count missing values for each column
        for column in all_columns:
            missing_count = sum(1 for row in rows if not row.get(column))
            missing_counts[column] = missing_count

            # Check if missing value threshold is exceeded
            missing_proportion = missing_count / len(rows) if rows else 0
            if missing_proportion > self.missing_value_threshold:
                # This is a warning about data quality, not a blocking error
                error = ErrorClassifier.classify_error(
                    row_number=None,  # Column-level issue
                    column_name=column,
                    raw_value=None,
                    error_category=ErrorCategory.INCONSISTENT,
                    context={
                        "description": f"Column '{column}' has {missing_count} missing values ({missing_proportion:.1%})",
                        "suggestion": f"Review data quality for column '{column}' or consider imputing missing values"
                    }
                )
                error.severity = Severity.WARNING  # Make it non-blocking
                error.is_blocking = False
                errors.append(error)

        return errors, dict(missing_counts)

    def _check_duplicates(
        self,
        rows: List[Dict[str, Any]]
    ) -> Tuple[List[ValidationErrorDetail], int]:
        """Check for duplicate rows based on key columns."""
        errors = []
        seen = defaultdict(list)
        duplicate_count = 0

        # Track rows by key columns
        for row_idx, row in enumerate(rows):
            # Build key from available key columns
            key_parts = []
            for col in self.key_columns:
                if col in row:
                    key_parts.append(str(row.get(col, "")))

            key = tuple(key_parts)

            if key in seen:
                # Found a duplicate
                seen[key].append(row_idx)
                duplicate_count += 1

                # Only add error for the first duplicate occurrence
                if len(seen[key]) == 2:
                    errors.append(ErrorClassifier.create_duplicate_error(
                        row_number=row_idx,
                        key_columns=self.key_columns
                    ))
            else:
                seen[key] = [row_idx]

        return errors, duplicate_count

    def _check_outliers(
        self,
        rows: List[Dict[str, Any]],
        source_type: str
    ) -> Tuple[List[ValidationErrorDetail], int]:
        """Check for statistical outliers in numeric columns."""
        errors = []
        outlier_count = 0

        # Numeric columns to check for outliers
        numeric_columns = ["quantity", "revenue", "price"]

        for column in numeric_columns:
            # Extract non-null numeric values
            values = []
            row_indices = []

            for row_idx, row in enumerate(rows):
                value = row.get(column)
                if value is not None and value != "":
                    try:
                        num_value = float(value)
                        values.append(num_value)
                        row_indices.append(row_idx)
                    except (ValueError, TypeError):
                        continue

            # Need at least some data points for outlier detection
            if len(values) < 10:
                continue

            # Calculate mean and standard deviation
            mean_value = statistics.mean(values)
            if len(values) > 1:
                stdev_value = statistics.stdev(values)
            else:
                stdev_value = 0

            # Detect outliers (more than N standard deviations from mean)
            if stdev_value > 0:
                threshold = self.outlier_std_dev * stdev_value

                for value, row_idx in zip(values, row_indices):
                    if abs(value - mean_value) > threshold:
                        std_devs = abs(value - mean_value) / stdev_value

                        errors.append(ErrorClassifier.create_outlier_error(
                            row_number=row_idx,
                            column_name=column,
                            raw_value=value,
                            std_dev=std_devs
                        ))
                        outlier_count += 1

        return errors, outlier_count

    def _check_consistency(
        self,
        rows: List[Dict[str, Any]],
        source_type: str
    ) -> List[ValidationErrorDetail]:
        """Check for data consistency issues."""
        errors = []

        # Check revenue vs price*quantity consistency
        if source_type == "transaction":
            for row_idx, row in enumerate(rows):
                revenue = row.get("revenue")
                price = row.get("price")
                quantity = row.get("quantity")

                # If revenue is provided but not price or quantity, flag as potential inconsistency
                if revenue is not None and (price is None or quantity is None):
                    error = ErrorClassifier.classify_error(
                        row_number=row_idx,
                        column_name="revenue",
                        raw_value=str(revenue),
                        error_category=ErrorCategory.INCONSISTENT,
                        context={
                            "description": "Revenue provided but price or quantity missing",
                            "suggestion": "Provide both price and quantity for accurate revenue validation"
                        }
                    )
                    error.severity = Severity.WARNING
                    error.is_blocking = False
                    errors.append(error)

        # Check for negative values where not appropriate
        for row_idx, row in enumerate(rows):
            # Check for negative quantities
            quantity = row.get("quantity")
            if quantity is not None:
                try:
                    quantity_float = float(quantity)
                    if quantity_float < 0:
                        error = ErrorClassifier.classify_error(
                            row_number=row_idx,
                            column_name="quantity",
                            raw_value=str(quantity),
                            error_category=ErrorCategory.OUT_OF_RANGE,
                            context={
                                "description": "Negative quantity detected",
                                "suggestion": "Quantities should be non-negative"
                            }
                        )
                        errors.append(error)
                except (ValueError, TypeError):
                    pass

            # Check for negative prices
            price = row.get("price")
            if price is not None:
                try:
                    price_float = float(price)
                    if price_float < 0:
                        error = ErrorClassifier.classify_error(
                            row_number=row_idx,
                            column_name="price",
                            raw_value=str(price),
                            error_category=ErrorCategory.OUT_OF_RANGE,
                            context={
                                "description": "Negative price detected",
                                "suggestion": "Prices should be non-negative"
                            }
                        )
                        errors.append(error)
                except (ValueError, TypeError):
                    pass

        return errors


# Convenience functions for data quality validation
def validate_data_quality(
    rows: List[Dict[str, Any]],
    source_type: str = "transaction",
    missing_threshold: float = 0.5,
    outlier_std_dev: float = 3.0,
    key_columns: Optional[List[str]] = None
) -> ValidationResult:
    """
    Convenience function to validate data quality.

    Args:
        rows: Data rows to validate
        source_type: Type of data
        missing_threshold: Proportion of missing values allowed
        outlier_std_dev: Standard deviations for outlier detection
        key_columns: Columns for duplicate detection

    Returns:
        ValidationResult
    """
    validator = DataQualityValidator(
        missing_value_threshold=missing_threshold,
        outlier_std_dev=outlier_std_dev,
        key_columns=key_columns
    )
    return validator.validate_data_quality(rows, source_type)


def check_missing_values(
    rows: List[Dict[str, Any]]
) -> Dict[str, int]:
    """
    Check for missing values by column (convenience function).

    Args:
        rows: Data rows to check

    Returns:
        Dictionary mapping column names to missing value counts
    """
    validator = DataQualityValidator()
    _, missing_counts = validator._check_missing_values(rows, "transaction")
    return missing_counts


def check_duplicates(
    rows: List[Dict[str, Any]],
    key_columns: Optional[List[str]] = None
) -> int:
    """
    Check for duplicate rows (convenience function).

    Args:
        rows: Data rows to check
        key_columns: Columns to use for duplicate detection

    Returns:
        Number of duplicate rows found
    """
    validator = DataQualityValidator(key_columns=key_columns)
    _, duplicate_count = validator._check_duplicates(rows)
    return duplicate_count


def check_outliers(
    rows: List[Dict[str, Any]],
    std_dev: float = 3.0
) -> List[ValidationErrorDetail]:
    """
    Check for statistical outliers (convenience function).

    Args:
        rows: Data rows to check
        std_dev: Standard deviations for outlier detection

    Returns:
        List of outlier errors found
    """
    validator = DataQualityValidator(outlier_std_dev=std_dev)
    outlier_errors, _ = validator._check_outliers(rows, "transaction")
    return outlier_errors
