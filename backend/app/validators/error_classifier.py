"""Error classification and severity assignment for validation errors."""

from typing import Optional, Dict, Any
from datetime import datetime
import logging

from app.schemas.validation import (
    ValidationErrorDetail, ErrorType, ErrorCategory, Severity
)

logger = logging.getLogger(__name__)


class ErrorClassifier:
    """
    Classifies validation errors by type, category, and severity.
    Generates actionable error messages and suggestions.
    """

    # Error type to category mapping
    ERROR_TYPE_CATEGORIES = {
        ErrorType.VALIDATION_ERROR: [
            ErrorCategory.MISSING_REQUIRED,
            ErrorCategory.INVALID_TYPE,
            ErrorCategory.INVALID_FORMAT,
            ErrorCategory.OUT_OF_RANGE,
            ErrorCategory.REFERENCE_NOT_FOUND
        ],
        ErrorType.BUSINESS_RULE: [
            ErrorCategory.CALCULATION,
            ErrorCategory.CONSTRAINT,
            ErrorCategory.OUT_OF_RANGE
        ],
        ErrorType.DATA_QUALITY: [
            ErrorCategory.DUPLICATE,
            ErrorCategory.OUTLIER,
            ErrorCategory.INCONSISTENT
        ],
        ErrorType.PARSING_ERROR: [
            ErrorCategory.INVALID_FORMAT,
            ErrorCategory.INVALID_TYPE
        ],
        ErrorType.SYSTEM_ERROR: [
            ErrorCategory.CONSTRAINT
        ]
    }

    # Default severity for each error category
    CATEGORY_SEVERITY = {
        ErrorCategory.MISSING_REQUIRED: Severity.ERROR,
        ErrorCategory.INVALID_TYPE: Severity.ERROR,
        ErrorCategory.INVALID_FORMAT: Severity.ERROR,
        ErrorCategory.OUT_OF_RANGE: Severity.ERROR,
        ErrorCategory.REFERENCE_NOT_FOUND: Severity.ERROR,
        ErrorCategory.DUPLICATE: Severity.ERROR,
        ErrorCategory.INCONSISTENT: Severity.WARNING,
        ErrorCategory.OUTLIER: Severity.WARNING,
        ErrorCategory.CALCULATION: Severity.WARNING,
        ErrorCategory.CONSTRAINT: Severity.ERROR
    }

    # Common error messages and suggestions
    ERROR_MESSAGES = {
        ErrorCategory.MISSING_REQUIRED: {
            "message": "Required field '{column}' is missing",
            "suggestion": "Provide a value for '{column}' to proceed with import"
        },
        ErrorCategory.INVALID_TYPE: {
            "message": "Invalid value type for '{column}': expected {expected_type}, got {actual_value}",
            "suggestion": "Ensure '{column}' contains {expected_type} values"
        },
        ErrorCategory.INVALID_FORMAT: {
            "message": "Invalid format for '{column}': '{value}' does not match expected format",
            "suggestion": "Check that '{column}' follows the correct format: {expected_format}"
        },
        ErrorCategory.OUT_OF_RANGE: {
            "message": "Value '{value}' for '{column}' is out of valid range [{min}, {max}]",
            "suggestion": "Ensure '{column}' value is between {min} and {max}"
        },
        ErrorCategory.REFERENCE_NOT_FOUND: {
            "message": "Reference '{value}' in '{column}' not found in master data",
            "suggestion": "Verify that '{value}' exists in the reference data for '{column}'"
        },
        ErrorCategory.DUPLICATE: {
            "message": "Duplicate row detected: combination of {columns} already exists",
            "suggestion": "Remove duplicate rows based on {columns} combination"
        },
        ErrorCategory.INCONSISTENT: {
            "message": "Data inconsistency detected: '{description}'",
            "suggestion": "Review and correct inconsistent data: {suggestion}"
        },
        ErrorCategory.OUTLIER: {
            "message": "Statistical outlier detected in '{column}': value '{value}' is {std_dev} standard deviations from mean",
            "suggestion": "Review the outlier value '{value}' in '{column}' for accuracy"
        },
        ErrorCategory.CALCULATION: {
            "message": "Calculation mismatch: {description}",
            "suggestion": "Verify the calculation: {suggestion}"
        },
        ErrorCategory.CONSTRAINT: {
            "message": "Business constraint violated: {description}",
            "suggestion": "Ensure data complies with business rule: {suggestion}"
        }
    }

    @classmethod
    def classify_error(
        cls,
        row_number: Optional[int],
        column_name: Optional[str],
        raw_value: Optional[str],
        error_category: ErrorCategory,
        context: Optional[Dict[str, Any]] = None
    ) -> ValidationErrorDetail:
        """
        Classify a validation error with appropriate type, severity, and messages.

        Args:
            row_number: Row where error occurred
            column_name: Column where error occurred
            raw_value: Value that caused the error
            error_category: Category of error
            context: Additional context for error generation

        Returns:
            ValidationErrorDetail with complete error classification
        """
        # Determine error type from category
        error_type = cls._determine_error_type(error_category)

        # Determine severity from category
        severity = cls.CATEGORY_SEVERITY.get(error_category, Severity.ERROR)

        # Determine if blocking (errors block, warnings don't)
        is_blocking = (severity == Severity.ERROR)

        # Generate error message and suggestion
        error_message, suggestion = cls._generate_error_messages(
            error_category, column_name, raw_value, context
        )

        # Build additional context string
        context_str = cls._build_context_string(error_category, context)

        return ValidationErrorDetail(
            row_number=row_number,
            column_name=column_name,
            raw_value=raw_value,
            error_type=error_type,
            error_category=error_category,
            severity=severity,
            is_blocking=is_blocking,
            error_message=error_message,
            suggestion=suggestion,
            context=context_str,
            meta_info=context or {}
        )

    @classmethod
    def _determine_error_type(cls, category: ErrorCategory) -> ErrorType:
        """Determine error type from error category."""
        for error_type, categories in cls.ERROR_TYPE_CATEGORIES.items():
            if category in categories:
                return error_type
        return ErrorType.VALIDATION_ERROR  # Default

    @classmethod
    def _generate_error_messages(
        cls,
        category: ErrorCategory,
        column_name: Optional[str],
        raw_value: Optional[str],
        context: Optional[Dict[str, Any]]
    ) -> tuple[str, Optional[str]]:
        """
        Generate error message and suggestion for the given category.

        Args:
            category: Error category
            column_name: Column where error occurred
            raw_value: Value that caused error
            context: Additional context for message generation

        Returns:
            Tuple of (error_message, suggestion)
        """
        templates = cls.ERROR_MESSAGES.get(category, {})

        # Build substitution dictionary
        subs = {
            "column": column_name or "unknown",
            "value": str(raw_value) if raw_value is not None else "null",
            "actual_value": str(raw_value) if raw_value is not None else "null",
            "expected_type": context.get("expected_type", "valid") if context else "valid",
            "expected_format": context.get("expected_format", "expected format") if context else "expected format",
            "min": context.get("min_value", "minimum") if context else "minimum",
            "max": context.get("max_value", "maximum") if context else "maximum",
            "columns": context.get("key_columns", "key fields") if context else "key fields",
            "std_dev": context.get("std_dev", "many") if context else "many",
            "description": context.get("description", "see details") if context else "see details",
            "suggestion": context.get("suggestion", "review data") if context else "review data"
        }

        # Generate message
        message_template = templates.get("message", "Validation error in '{column}'")
        error_message = message_template.format(**subs)

        # Generate suggestion
        suggestion = None
        if "suggestion" in templates:
            suggestion_template = templates["suggestion"]
            suggestion = suggestion_template.format(**subs)

        return error_message, suggestion

    @classmethod
    def _build_context_string(
        cls,
        category: ErrorCategory,
        context: Optional[Dict[str, Any]]
    ) -> Optional[str]:
        """Build a context string for additional error information."""
        if not context:
            return None

        context_parts = []

        # Add relevant context based on category
        if category == ErrorCategory.CALCULATION:
            if "expected_value" in context and "actual_value" in context:
                context_parts.append(
                    f"Expected: {context['expected_value']}, Actual: {context['actual_value']}"
                )
        elif category == ErrorCategory.OUT_OF_RANGE:
            if "valid_range" in context:
                context_parts.append(f"Valid range: {context['valid_range']}")
        elif category == ErrorCategory.REFERENCE_NOT_FOUND:
            if "reference_table" in context:
                context_parts.append(f"Reference table: {context['reference_table']}")

        return "; ".join(context_parts) if context_parts else None

    @classmethod
    def create_missing_field_error(
        cls,
        row_number: int,
        column_name: str
    ) -> ValidationErrorDetail:
        """Create a missing required field error."""
        return cls.classify_error(
            row_number=row_number,
            column_name=column_name,
            raw_value=None,
            error_category=ErrorCategory.MISSING_REQUIRED
        )

    @classmethod
    def create_invalid_type_error(
        cls,
        row_number: int,
        column_name: str,
        raw_value: str,
        expected_type: str
    ) -> ValidationErrorDetail:
        """Create an invalid data type error."""
        return cls.classify_error(
            row_number=row_number,
            column_name=column_name,
            raw_value=raw_value,
            error_category=ErrorCategory.INVALID_TYPE,
            context={"expected_type": expected_type}
        )

    @classmethod
    def create_invalid_format_error(
        cls,
        row_number: int,
        column_name: str,
        raw_value: str,
        expected_format: str
    ) -> ValidationErrorDetail:
        """Create an invalid format error."""
        return cls.classify_error(
            row_number=row_number,
            column_name=column_name,
            raw_value=raw_value,
            error_category=ErrorCategory.INVALID_FORMAT,
            context={"expected_format": expected_format}
        )

    @classmethod
    def create_out_of_range_error(
        cls,
        row_number: int,
        column_name: str,
        raw_value: str,
        min_value: float,
        max_value: float
    ) -> ValidationErrorDetail:
        """Create an out of range error."""
        return cls.classify_error(
            row_number=row_number,
            column_name=column_name,
            raw_value=raw_value,
            error_category=ErrorCategory.OUT_OF_RANGE,
            context={
                "min_value": min_value,
                "max_value": max_value,
                "valid_range": f"[{min_value}, {max_value}]"
            }
        )

    @classmethod
    def create_reference_error(
        cls,
        row_number: int,
        column_name: str,
        raw_value: str,
        reference_table: str
    ) -> ValidationErrorDetail:
        """Create a reference not found error."""
        return cls.classify_error(
            row_number=row_number,
            column_name=column_name,
            raw_value=raw_value,
            error_category=ErrorCategory.REFERENCE_NOT_FOUND,
            context={"reference_table": reference_table}
        )

    @classmethod
    def create_duplicate_error(
        cls,
        row_number: int,
        key_columns: list[str]
    ) -> ValidationErrorDetail:
        """Create a duplicate row error."""
        columns_str = ", ".join(key_columns)
        return cls.classify_error(
            row_number=row_number,
            column_name=None,  # Multiple columns involved
            raw_value=None,
            error_category=ErrorCategory.DUPLICATE,
            context={"key_columns": columns_str}
        )

    @classmethod
    def create_outlier_error(
        cls,
        row_number: int,
        column_name: str,
        raw_value: float,
        std_dev: float
    ) -> ValidationErrorDetail:
        """Create a statistical outlier error."""
        return cls.classify_error(
            row_number=row_number,
            column_name=column_name,
            raw_value=str(raw_value),
            error_category=ErrorCategory.OUTLIER,
            context={"std_dev": f"{std_dev:.1f}"}
        )

    @classmethod
    def create_calculation_error(
        cls,
        row_number: int,
        description: str,
        expected: float,
        actual: float,
        suggestion: str
    ) -> ValidationErrorDetail:
        """Create a calculation mismatch error."""
        return cls.classify_error(
            row_number=row_number,
            column_name=None,
            raw_value=str(actual),
            error_category=ErrorCategory.CALCULATION,
            context={
                "description": description,
                "expected_value": expected,
                "actual_value": actual,
                "suggestion": suggestion
            }
        )

    @classmethod
    def create_constraint_error(
        cls,
        row_number: int,
        description: str,
        suggestion: str
    ) -> ValidationErrorDetail:
        """Create a business constraint violation error."""
        return cls.classify_error(
            row_number=row_number,
            column_name=None,
            raw_value=None,
            error_category=ErrorCategory.CONSTRAINT,
            context={
                "description": description,
                "suggestion": suggestion
            }
        )


# Convenience functions for common error types
def missing_field_error(row_number: int, column_name: str) -> ValidationErrorDetail:
    """Create a missing required field error."""
    return ErrorClassifier.create_missing_field_error(row_number, column_name)


def invalid_type_error(
    row_number: int,
    column_name: str,
    raw_value: str,
    expected_type: str
) -> ValidationErrorDetail:
    """Create an invalid data type error."""
    return ErrorClassifier.create_invalid_type_error(
        row_number, column_name, raw_value, expected_type
    )


def invalid_format_error(
    row_number: int,
    column_name: str,
    raw_value: str,
    expected_format: str
) -> ValidationErrorDetail:
    """Create an invalid format error."""
    return ErrorClassifier.create_invalid_format_error(
        row_number, column_name, raw_value, expected_format
    )


def out_of_range_error(
    row_number: int,
    column_name: str,
    raw_value: str,
    min_value: float,
    max_value: float
) -> ValidationErrorDetail:
    """Create an out of range error."""
    return ErrorClassifier.create_out_of_range_error(
        row_number, column_name, raw_value, min_value, max_value
    )


def reference_error(
    row_number: int,
    column_name: str,
    raw_value: str,
    reference_table: str
) -> ValidationErrorDetail:
    """Create a reference not found error."""
    return ErrorClassifier.create_reference_error(
        row_number, column_name, raw_value, reference_table
    )


def duplicate_error(row_number: int, key_columns: list[str]) -> ValidationErrorDetail:
    """Create a duplicate row error."""
    return ErrorClassifier.create_duplicate_error(row_number, key_columns)


def outlier_error(
    row_number: int,
    column_name: str,
    raw_value: float,
    std_dev: float
) -> ValidationErrorDetail:
    """Create a statistical outlier error."""
    return ErrorClassifier.create_outlier_error(
        row_number, column_name, raw_value, std_dev
    )


def calculation_error(
    row_number: int,
    description: str,
    expected: float,
    actual: float,
    suggestion: str
) -> ValidationErrorDetail:
    """Create a calculation mismatch error."""
    return ErrorClassifier.create_calculation_error(
        row_number, description, expected, actual, suggestion
    )


def constraint_error(
    row_number: int,
    description: str,
    suggestion: str
) -> ValidationErrorDetail:
    """Create a business constraint violation error."""
    return ErrorClassifier.create_constraint_error(
        row_number, description, suggestion
    )
