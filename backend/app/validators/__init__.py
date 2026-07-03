"""Validators package for data validation.

This package provides comprehensive validation capabilities:
- Error classification and severity assignment
- Schema validation (columns, types, formats)
- Business rules validation (calculations, constraints)
- Data quality validation (missing values, duplicates, outliers)
"""

from app.validators.error_classifier import (
    ErrorClassifier,
    missing_field_error,
    invalid_type_error,
    invalid_format_error,
    out_of_range_error,
    reference_error,
    duplicate_error,
    outlier_error,
    calculation_error,
    constraint_error
)

from app.validators.schema_validator import (
    SchemaValidator,
    ColumnDefinition,
    TRANSACTION_COLUMNS_DEF,
    LOOKUP_COLUMNS_DEF,
    validate_schema,
    get_required_columns
)

from app.validators.business_rules_validator import (
    BusinessRulesValidator,
    validate_business_rules,
    validate_revenue_only
)

from app.validators.data_quality_validator import (
    DataQualityValidator,
    validate_data_quality,
    check_missing_values,
    check_duplicates,
    check_outliers
)

__all__ = [
    # Error classifier
    "ErrorClassifier",
    "missing_field_error",
    "invalid_type_error",
    "invalid_format_error",
    "out_of_range_error",
    "reference_error",
    "duplicate_error",
    "outlier_error",
    "calculation_error",
    "constraint_error",

    # Schema validator
    "SchemaValidator",
    "ColumnDefinition",
    "TRANSACTION_COLUMNS_DEF",
    "LOOKUP_COLUMNS_DEF",
    "validate_schema",
    "get_required_columns",

    # Business rules validator
    "BusinessRulesValidator",
    "validate_business_rules",
    "validate_revenue_only",

    # Data quality validator
    "DataQualityValidator",
    "validate_data_quality",
    "check_missing_values",
    "check_duplicates",
    "check_outliers",
]
