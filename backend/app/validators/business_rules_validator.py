"""Business rules validation for revenue calculations, date ranges, and constraints."""

from typing import List, Dict, Any, Optional, Set
from datetime import datetime, timedelta
import logging

from app.schemas.validation import (
    ValidationErrorDetail, ValidationResult, ValidationStatistics,
    ValidationStage, ErrorCategory, Severity
)
from app.validators.error_classifier import ErrorClassifier

logger = logging.getLogger(__name__)


class BusinessRulesValidator:
    """
    Validates business rules including:
    - Revenue = price × quantity consistency
    - Date range validation (no future dates for historical data)
    - Reference data existence (product_id, location_id)
    - Numeric value ranges (no negative quantities)
    - Price and quantity validation
    """

    def __init__(
        self,
        revenue_tolerance: float = 0.01,  # 1% tolerance
        allow_future_dates: bool = False,
        min_quantity: float = 0,
        max_quantity: Optional[float] = None,
        min_price: float = 0,
        max_price: Optional[float] = None
    ):
        """
        Initialize business rules validator.

        Args:
            revenue_tolerance: Allowed tolerance for revenue calculation (default 1%)
            allow_future_dates: Whether to allow future dates in historical data
            min_quantity: Minimum allowed quantity
            max_quantity: Maximum allowed quantity
            min_price: Minimum allowed price
            max_price: Maximum allowed price
        """
        self.revenue_tolerance = revenue_tolerance
        self.allow_future_dates = allow_future_dates
        self.min_quantity = min_quantity
        self.max_quantity = max_quantity
        self.min_price = min_price
        self.max_price = max_price

    def validate_business_rules(
        self,
        rows: List[Dict[str, Any]],
        source_type: str = "transaction",
        reference_data: Optional[Dict[str, Set[str]]] = None
    ) -> ValidationResult:
        """
        Validate data against business rules.

        Args:
            rows: List of data rows to validate
            source_type: Type of data ('transaction', 'lookup', 'actuals')
            reference_data: Dictionary of reference data sets for validation
                           e.g., {'product_ids': {'P1', 'P2'}, 'location_ids': {'L1', 'L2'}}

        Returns:
            ValidationResult with business rules validation results
        """
        started_at = datetime.now()
        errors = []
        statistics = ValidationStatistics()

        if not rows:
            return ValidationResult(
                is_valid=False,
                can_import=False,
                current_stage=ValidationStage.BUSINESS_RULES,
                statistics=statistics,
                errors=[ErrorClassifier.create_constraint_error(
                    0, "No data to validate", "Provide at least one row of data"
                )],
                started_at=started_at,
                completed_at=datetime.now()
            )

        statistics.total_rows = len(rows)

        # Validate each row
        for row_idx, row in enumerate(rows):
            row_errors = self._validate_row(
                row, row_idx, source_type, reference_data
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
            current_stage=ValidationStage.BUSINESS_RULES,
            stage_percentage=100.0,
            statistics=statistics,
            errors=errors,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration
        )

    def _validate_row(
        self,
        row: Dict[str, Any],
        row_idx: int,
        source_type: str,
        reference_data: Optional[Dict[str, Set[str]]]
    ) -> List[ValidationErrorDetail]:
        """Validate a single row against business rules."""
        errors = []

        # Revenue calculation validation
        if source_type == "transaction":
            revenue_errors = self._validate_revenue_calculation(row, row_idx)
            errors.extend(revenue_errors)

        # Date range validation
        date_errors = self._validate_date_range(row, row_idx, source_type)
        errors.extend(date_errors)

        # Quantity validation
        quantity_errors = self._validate_quantity(row, row_idx)
        errors.extend(quantity_errors)

        # Price validation
        price_errors = self._validate_price(row, row_idx)
        errors.extend(price_errors)

        # Reference data validation
        if reference_data:
            ref_errors = self._validate_reference_data(row, row_idx, reference_data)
            errors.extend(ref_errors)

        return errors

    def _validate_revenue_calculation(
        self,
        row: Dict[str, Any],
        row_idx: int
    ) -> List[ValidationErrorDetail]:
        """Validate revenue = price × quantity calculation."""
        errors = []

        revenue = row.get("revenue")
        price = row.get("price")
        quantity = row.get("quantity")

        # Only validate if all three fields are present
        if revenue is None or price is None or quantity is None:
            return errors

        try:
            revenue_float = float(revenue)
            price_float = float(price)
            quantity_float = float(quantity)

            expected_revenue = price_float * quantity_float

            # Check if revenue matches calculation within tolerance
            if expected_revenue != 0:
                difference = abs(revenue_float - expected_revenue)
                tolerance_amount = expected_revenue * self.revenue_tolerance

                if difference > tolerance_amount:
                    errors.append(ErrorClassifier.create_calculation_error(
                        row_idx=row_idx,
                        description=f"Revenue ({revenue_float:.2f}) doesn't match price × quantity ({price_float:.2f} × {quantity_float:.2f} = {expected_revenue:.2f})",
                        expected=expected_revenue,
                        actual=revenue_float,
                        suggestion=f"Ensure revenue equals price × quantity, or check if values are within {self.revenue_tolerance * 100}% tolerance"
                    ))

        except (ValueError, TypeError) as e:
            logger.warning(f"Could not validate revenue calculation for row {row_idx}: {e}")

        return errors

    def _validate_date_range(
        self,
        row: Dict[str, Any],
        row_idx: int,
        source_type: str
    ) -> List[ValidationErrorDetail]:
        """Validate date is not in future for historical data."""
        errors = []

        date_value = row.get("date")
        if not date_value:
            return errors

        try:
            # Parse date
            if isinstance(date_value, str):
                parsed_date = datetime.fromisoformat(date_value)
            elif isinstance(date_value, datetime):
                parsed_date = date_value
            else:
                return errors

            # Check for future dates
            if not self.allow_future_dates:
                if source_type in ["transaction", "sales", "actuals"]:
                    today = datetime.now().date()
                    data_date = parsed_date.date()

                    # Allow small buffer for time zones and processing delays
                    if data_date > today + timedelta(days=1):
                        errors.append(ErrorClassifier.create_constraint_error(
                            row_idx=row_idx,
                            description=f"Date '{date_value}' is in the future for {source_type} data",
                            suggestion=f"Ensure dates are not in the future, or set allow_future_dates=True for forecast data"
                        ))

        except (ValueError, TypeError) as e:
            logger.warning(f"Could not validate date range for row {row_idx}: {e}")

        return errors

    def _validate_quantity(
        self,
        row: Dict[str, Any],
        row_idx: int
    ) -> List[ValidationErrorDetail]:
        """Validate quantity values."""
        errors = []

        quantity = row.get("quantity")
        if quantity is None or quantity == "":
            return errors

        try:
            quantity_float = float(quantity)

            # Check minimum
            if quantity_float < self.min_quantity:
                errors.append(ErrorClassifier.create_out_of_range_error(
                    row_idx=row_idx,
                    column_name="quantity",
                    raw_value=str(quantity),
                    min_value=self.min_quantity,
                    max_value=self.max_quantity if self.max_quantity else float('inf')
                ))

            # Check maximum
            if self.max_quantity is not None and quantity_float > self.max_quantity:
                errors.append(ErrorClassifier.create_out_of_range_error(
                    row_idx=row_idx,
                    column_name="quantity",
                    raw_value=str(quantity),
                    min_value=self.min_quantity,
                    max_value=self.max_quantity
                ))

        except (ValueError, TypeError):
            # Type error already caught in schema validation
            pass

        return errors

    def _validate_price(
        self,
        row: Dict[str, Any],
        row_idx: int
    ) -> List[ValidationErrorDetail]:
        """Validate price values."""
        errors = []

        price = row.get("price")
        if price is None or price == "":
            return errors

        try:
            price_float = float(price)

            # Check minimum
            if price_float < self.min_price:
                errors.append(ErrorClassifier.create_out_of_range_error(
                    row_idx=row_idx,
                    column_name="price",
                    raw_value=str(price),
                    min_value=self.min_price,
                    max_value=self.max_price if self.max_price else float('inf')
                ))

            # Check maximum
            if self.max_price is not None and price_float > self.max_price:
                errors.append(ErrorClassifier.create_out_of_range_error(
                    row_idx=row_idx,
                    column_name="price",
                    raw_value=str(price),
                    min_value=self.min_price,
                    max_value=self.max_price
                ))

        except (ValueError, TypeError):
            # Type error already caught in schema validation
            pass

        return errors

    def _validate_reference_data(
        self,
        row: Dict[str, Any],
        row_idx: int,
        reference_data: Dict[str, Set[str]]
    ) -> List[ValidationErrorDetail]:
        """Validate reference data exists."""
        errors = []

        # Validate product_id
        if "product_ids" in reference_data:
            product_id = row.get("product_id")
            if product_id and product_id not in reference_data["product_ids"]:
                errors.append(ErrorClassifier.create_reference_error(
                    row_idx=row_idx,
                    column_name="product_id",
                    raw_value=str(product_id),
                    reference_table="products"
                ))

        # Validate location_id
        if "location_ids" in reference_data:
            location_id = row.get("location_id")
            if location_id and location_id not in reference_data["location_ids"]:
                errors.append(ErrorClassifier.create_reference_error(
                    row_idx=row_idx,
                    column_name="location_id",
                    raw_value=str(location_id),
                    reference_table="locations"
                ))

        return errors


# Convenience functions for business rules validation
def validate_business_rules(
    rows: List[Dict[str, Any]],
    source_type: str = "transaction",
    reference_data: Optional[Dict[str, Set[str]]] = None,
    revenue_tolerance: float = 0.01,
    allow_future_dates: bool = False
) -> ValidationResult:
    """
    Convenience function to validate business rules.

    Args:
        rows: Data rows to validate
        source_type: Type of data
        reference_data: Reference data sets
        revenue_tolerance: Allowed tolerance for revenue calculation
        allow_future_dates: Whether to allow future dates

    Returns:
        ValidationResult
    """
    validator = BusinessRulesValidator(
        revenue_tolerance=revenue_tolerance,
        allow_future_dates=allow_future_dates
    )
    return validator.validate_business_rules(rows, source_type, reference_data)


def validate_revenue_only(
    rows: List[Dict[str, Any]],
    tolerance: float = 0.01
) -> List[ValidationErrorDetail]:
    """
    Validate only revenue calculations (convenience function).

    Args:
        rows: Data rows to validate
        tolerance: Allowed tolerance for revenue calculation

    Returns:
        List of revenue calculation errors
    """
    validator = BusinessRulesValidator(revenue_tolerance=tolerance)
    result = validator.validate_business_rules(rows, "transaction")

    # Filter only revenue calculation errors
    revenue_errors = [
        e for e in result.errors
        if e.error_category == ErrorCategory.CALCULATION
    ]

    return revenue_errors
