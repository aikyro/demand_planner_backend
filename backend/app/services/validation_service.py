"""Main validation service orchestrating all validators with batch processing."""

from typing import List, Dict, Any, Optional, Set, Iterator, Callable
from datetime import datetime
import logging
import pandas as pd

from app.schemas.validation import (
    ValidationResult, ValidationStatistics, ValidationStage,
    ValidationErrorDetail, ValidationConfig, BatchValidationResult,
    ValidationPreview, ErrorCategory, Severity
)
from app.validators.schema_validator import SchemaValidator
from app.validators.business_rules_validator import BusinessRulesValidator
from app.validators.data_quality_validator import DataQualityValidator
from app.validators.error_classifier import ErrorClassifier

logger = logging.getLogger(__name__)


class ValidationService:
    """
    Main validation service that orchestrates all validators.
    Provides comprehensive validation with batch processing support.
    """

    def __init__(self, config: Optional[ValidationConfig] = None):
        """
        Initialize validation service.

        Args:
            config: Validation configuration (uses defaults if not provided)
        """
        self.config = config or ValidationConfig()

        # Initialize validators
        self.schema_validator = SchemaValidator()
        self.business_rules_validator = BusinessRulesValidator(
            revenue_tolerance=self.config.revenue_tolerance,
            allow_future_dates=self.config.allow_future_dates,
            min_quantity=self.config.min_quantity,
            max_quantity=self.config.max_quantity,
            min_price=self.config.min_price,
            max_price=self.config.max_price
        )
        self.data_quality_validator = DataQualityValidator(
            missing_value_threshold=self.config.missing_value_threshold,
            duplicate_threshold=self.config.duplicate_threshold,
            outlier_std_dev=self.config.outlier_std_dev
        )

    def validate_all(
        self,
        rows: List[Dict[str, Any]],
        source_type: str = "transaction",
        reference_data: Optional[Dict[str, Set[str]]] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> ValidationResult:
        """
        Run complete validation pipeline: schema → business rules → data quality.

        Args:
            rows: List of data rows to validate
            source_type: Type of data ('transaction' or 'lookup')
            reference_data: Dictionary of reference data sets
            progress_callback: Optional callback for progress updates

        Returns:
            ValidationResult with complete validation results
        """
        started_at = datetime.now()
        all_errors = []
        statistics = ValidationStatistics()

        if progress_callback:
            progress_callback(0.0, "Starting validation")

        if not rows:
            return ValidationResult(
                is_valid=False,
                can_import=False,
                current_stage=ValidationStage.FAILED,
                statistics=statistics,
                errors=[ErrorClassifier.create_constraint_error(
                    0, "No data to validate", "Provide at least one row of data"
                )],
                started_at=started_at,
                completed_at=datetime.now()
            )

        statistics.total_rows = len(rows)

        # Stage 1: Schema Validation
        if self.config.enable_schema_validation:
            if progress_callback:
                progress_callback(10.0, "Validating schema")

            schema_result = self.schema_validator.validate_schema(rows, source_type)
            all_errors.extend(schema_result.errors)

            if progress_callback:
                progress_callback(30.0, "Schema validation complete")

        # Stage 2: Business Rules Validation (Commented out per senior requirement)
        # if self.config.enable_business_rules:
        #     if progress_callback:
        #         progress_callback(40.0, "Validating business rules")
        # 
        #     business_result = self.business_rules_validator.validate_business_rules(
        #         rows, source_type, reference_data
        #     )
        #     all_errors.extend(business_result.errors)
        # 
        #     if progress_callback:
        #         progress_callback(60.0, "Business rules validation complete")

        # Stage 3: Data Quality Validation (Commented out per senior requirement)
        # if self.config.enable_data_quality:
        #     if progress_callback:
        #         progress_callback(70.0, "Validating data quality")
        # 
        #     quality_result = self.data_quality_validator.validate_data_quality(
        #         rows, source_type
        #     )
        #     all_errors.extend(quality_result.errors)
        # 
        #     # Add quality metrics to statistics
        #     statistics.missing_values = quality_result.statistics.missing_values
        #     statistics.duplicate_count = quality_result.statistics.duplicate_count
        #     statistics.outlier_count = quality_result.statistics.outlier_count
        # 
        #     if progress_callback:
        #         progress_callback(90.0, "Data quality validation complete")

        # Calculate final statistics
        statistics.total_errors = len([e for e in all_errors if e.severity == Severity.ERROR])
        statistics.total_warnings = len([e for e in all_errors if e.severity == Severity.WARNING])
        statistics.blocking_errors = len([e for e in all_errors if e.is_blocking])
        statistics.error_rows = len(set(e.row_number for e in all_errors if e.row_number is not None))
        statistics.valid_rows = statistics.total_rows - statistics.error_rows
        statistics.warning_rows = len(set(
            e.row_number for e in all_errors
            if e.row_number is not None and e.severity == Severity.WARNING
        ))

        # Track errors by type and category
        for error in all_errors:
            statistics.errors_by_type[error.error_type] = \
                statistics.errors_by_type.get(error.error_type, 0) + 1
            statistics.errors_by_category[error.error_category] = \
                statistics.errors_by_category.get(error.error_category, 0) + 1

        completed_at = datetime.now()
        duration = (completed_at - started_at).total_seconds()
        statistics.duration_seconds = duration
        if duration > 0:
            statistics.rows_per_second = statistics.total_rows / duration

        # Determine validity
        is_valid = statistics.blocking_errors == 0
        can_import = is_valid

        # Limit errors to display
        display_errors = all_errors[:self.config.max_errors_to_display]

        if progress_callback:
            progress_callback(100.0, "Validation complete")

        return ValidationResult(
            is_valid=is_valid,
            can_import=can_import,
            current_stage=ValidationStage.COMPLETED,
            stage_percentage=100.0,
            statistics=statistics,
            errors=display_errors,
            source_type=source_type,
            validation_rules=self._get_active_rules(),
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration
        )

    def validate_in_batches(
        self,
        rows: List[Dict[str, Any]],
        source_type: str = "transaction",
        reference_data: Optional[Dict[str, Set[str]]] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> Iterator[BatchValidationResult]:
        """
        Validate large dataset in batches to manage memory usage.

        Args:
            rows: List of data rows to validate
            source_type: Type of data
            reference_data: Reference data sets
            progress_callback: Optional progress callback

        Yields:
            BatchValidationResult for each batch
        """
        if not rows:
            yield BatchValidationResult(
                batch_id=0,
                start_row=0,
                end_row=0,
                row_count=0,
                errors=[ErrorClassifier.create_constraint_error(
                    0, "No data to validate", "Provide at least one row of data"
                )]
            )
            return

        batch_size = self.config.batch_size
        total_rows = len(rows)
        total_batches = (total_rows + batch_size - 1) // batch_size

        for batch_idx in range(total_batches):
            start_row = batch_idx * batch_size
            end_row = min(start_row + batch_size, total_rows)
            batch_rows = rows[start_row:end_row]

            started_at = datetime.now()

            # Validate this batch
            result = self.validate_all(
                batch_rows, source_type, reference_data, None
            )

            completed_at = datetime.now()
            duration = (completed_at - started_at).total_seconds()

            # Convert to batch result
            batch_errors = [
                ValidationErrorDetail(
                    row_number=e.row_number + start_row if e.row_number is not None else None,
                    column_name=e.column_name,
                    raw_value=e.raw_value,
                    error_type=e.error_type,
                    error_category=e.error_category,
                    severity=e.severity,
                    is_blocking=e.is_blocking,
                    error_message=e.error_message,
                    suggestion=e.suggestion,
                    context=e.context,
                    meta_info=e.meta_info,
                    created_at=e.created_at
                )
                for e in result.errors
            ]

            yield BatchValidationResult(
                batch_id=batch_idx + 1,
                start_row=start_row,
                end_row=end_row - 1,
                row_count=len(batch_rows),
                errors=batch_errors,
                valid_count=result.statistics.valid_rows,
                error_count=result.statistics.error_rows,
                duration_seconds=duration,
                rows_per_second=len(batch_rows) / duration if duration > 0 else None,
                processed_at=completed_at
            )

            if progress_callback:
                progress = ((batch_idx + 1) / total_batches) * 100
                progress_callback(progress, f"Processed batch {batch_idx + 1}/{total_batches}")

    def create_validation_preview(
        self,
        validation_result: ValidationResult
    ) -> ValidationPreview:
        """
        Create a preview of validation results for UI display.

        Args:
            validation_result: Complete validation result

        Returns:
            ValidationPreview for display
        """
        # Calculate valid percentage
        valid_percentage = (
            (validation_result.statistics.valid_rows / validation_result.statistics.total_rows * 100)
            if validation_result.statistics.total_rows > 0 else 0.0
        )

        # Get sample errors
        sample_errors = validation_result.errors[:self.config.max_errors_to_display]

        # Build error summary
        error_summary = {}
        for error in validation_result.errors:
            key = f"{error.error_category.value}:{error.severity.value}"
            error_summary[key] = error_summary.get(key, 0) + 1

        # Build quality issues summary
        quality_issues = {
            "missing_values": sum(validation_result.statistics.missing_values.values()),
            "duplicates": validation_result.statistics.duplicate_count,
            "outliers": validation_result.statistics.outlier_count
        }

        return ValidationPreview(
            is_valid=validation_result.is_valid,
            can_import=validation_result.can_import,
            total_rows=validation_result.statistics.total_rows,
            valid_percentage=valid_percentage,
            error_count=validation_result.statistics.total_errors,
            warning_count=validation_result.statistics.total_warnings,
            sample_errors=sample_errors,
            sample_size=min(self.config.max_errors_to_display, len(validation_result.errors)),
            error_summary=error_summary,
            quality_issues=quality_issues,
            validation_completed=validation_result.current_stage == ValidationStage.COMPLETED
        )

    def aggregate_batch_results(
        self,
        batch_results: List[BatchValidationResult]
    ) -> ValidationResult:
        """
        Aggregate multiple batch validation results into one complete result.

        Args:
            batch_results: List of batch validation results

        Returns:
            Aggregated ValidationResult
        """
        if not batch_results:
            return ValidationResult(
                is_valid=False,
                can_import=False,
                current_stage=ValidationStage.FAILED,
                statistics=ValidationStatistics(),
                errors=[],
                started_at=datetime.now(),
                completed_at=datetime.now()
            )

        # Aggregate statistics
        total_rows = sum(br.row_count for br in batch_results)
        total_errors = sum(len([e for e in br.errors if e.severity == Severity.ERROR]) for br in batch_results)
        total_warnings = sum(len([e for e in br.errors if e.severity == Severity.WARNING]) for br in batch_results)

        # Collect all errors
        all_errors = []
        for br in batch_results:
            all_errors.extend(br.errors)

        # Calculate error rows (unique row numbers)
        error_rows = len(set(e.row_number for e in all_errors if e.row_number is not None))

        # Build statistics
        statistics = ValidationStatistics(
            total_rows=total_rows,
            valid_rows=total_rows - error_rows,
            error_rows=error_rows,
            total_errors=total_errors,
            total_warnings=total_warnings,
            blocking_errors=len([e for e in all_errors if e.is_blocking])
        )

        # Track errors by type and category
        for error in all_errors:
            statistics.errors_by_type[error.error_type] = \
                statistics.errors_by_type.get(error.error_type, 0) + 1
            statistics.errors_by_category[error.error_category] = \
                statistics.errors_by_category.get(error.error_category, 0) + 1

        # Calculate timing
        started_at = min(br.processed_at for br in batch_results)
        completed_at = max(br.processed_at for br in batch_results)
        duration = (completed_at - started_at).total_seconds()

        statistics.duration_seconds = duration
        if duration > 0:
            statistics.rows_per_second = total_rows / duration

        is_valid = statistics.blocking_errors == 0
        can_import = is_valid

        return ValidationResult(
            is_valid=is_valid,
            can_import=can_import,
            current_stage=ValidationStage.COMPLETED,
            stage_percentage=100.0,
            statistics=statistics,
            errors=all_errors[:self.config.max_errors_to_display],
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration
        )

    def _get_active_rules(self) -> List[str]:
        """Get list of active validation rules."""
        rules = []

        if self.config.enable_schema_validation:
            rules.extend([
                "schema.column_presence",
                "schema.data_types",
                "schema.required_fields",
                "schema.format_validation",
                "schema.range_validation"
            ])

        if self.config.enable_business_rules:
            rules.extend([
                "business.revenue_calculation",
                "business.date_ranges",
                "business.quantity_validation",
                "business.price_validation",
                "business.reference_data"
            ])

        if self.config.enable_data_quality:
            rules.extend([
                "quality.missing_values",
                "quality.duplicates",
                "quality.outliers",
                "quality.consistency"
            ])

        return rules


# Convenience functions for validation service
def validate_data(
    rows: List[Dict[str, Any]],
    source_type: str = "transaction",
    reference_data: Optional[Dict[str, Set[str]]] = None,
    config: Optional[ValidationConfig] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None
) -> ValidationResult:
    """
    Convenience function to validate data with all validators.

    Args:
        rows: Data rows to validate
        source_type: Type of data
        reference_data: Reference data sets
        config: Validation configuration
        progress_callback: Optional progress callback

    Returns:
        ValidationResult
    """
    service = ValidationService(config)
    return service.validate_all(rows, source_type, reference_data, progress_callback)


def validate_large_dataset(
    rows: List[Dict[str, Any]],
    source_type: str = "transaction",
    reference_data: Optional[Dict[str, Set[str]]] = None,
    config: Optional[ValidationConfig] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None
) -> ValidationResult:
    """
    Validate large dataset using batch processing.

    Args:
        rows: Data rows to validate
        source_type: Type of data
        reference_data: Reference data sets
        config: Validation configuration
        progress_callback: Optional progress callback

    Returns:
        Aggregated ValidationResult
    """
    service = ValidationService(config)

    # Collect batch results
    batch_results = []
    for batch_result in service.validate_in_batches(
        rows, source_type, reference_data, progress_callback
    ):
        batch_results.append(batch_result)

    # Aggregate results
    return service.aggregate_batch_results(batch_results)
