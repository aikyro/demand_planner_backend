"""Comprehensive error handling for file parsing operations."""

from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
from pathlib import Path
import logging
import traceback

from app.schemas.files import ParserError, FileType, DataType


logger = logging.getLogger(__name__)


class ParserErrorHandler:
    """Handle and classify errors during file parsing operations."""

    # Error type classifications
    ERROR_TYPES = {
        "file_not_found": "File does not exist",
        "file_too_large": "File exceeds size limit",
        "invalid_format": "File format is invalid",
        "corrupted_file": "File is corrupted",
        "encoding_error": "File encoding error",
        "malformed_csv": "Malformed CSV structure",
        "excel_read_error": "Excel file read error",
        "json_structure_error": "Invalid JSON structure",
        "memory_error": "Insufficient memory",
        "io_error": "Input/output error",
        "permission_error": "File permission error",
        "validation_error": "Data validation error",
        "column_error": "Column-related error",
        "row_error": "Row-related error",
        "general_error": "General parsing error"
    }

    # Error categories
    ERROR_CATEGORIES = {
        "file": "File-level errors",
        "content": "Content-level errors",
        "system": "System-level errors",
        "validation": "Validation errors"
    }

    def __init__(self):
        """Initialize error handler."""
        self.errors: List[ParserError] = []
        self.warnings: List[ParserError] = []

    def handle_file_not_found(
        self,
        file_path: str,
        context: Optional[str] = None
    ) -> ParserError:
        """Handle file not found error."""
        error = ParserError(
            error_type="file_not_found",
            error_category="file",
            severity="error",
            message=f"File not found: {file_path}",
            context=context,
            is_blocking=True
        )
        self.errors.append(error)
        return error

    def handle_file_too_large(
        self,
        file_path: str,
        file_size_mb: float,
        max_size_mb: int,
        context: Optional[str] = None
    ) -> ParserError:
        """Handle file size exceeded error."""
        error = ParserError(
            error_type="file_too_large",
            error_category="file",
            severity="error",
            message=f"File size ({file_size_mb:.2f}MB) exceeds maximum ({max_size_mb}MB)",
            context=context,
            is_blocking=True
        )
        self.errors.append(error)
        return error

    def handle_invalid_format(
        self,
        file_path: str,
        detected_format: Optional[str],
        expected_format: FileType,
        context: Optional[str] = None
    ) -> ParserError:
        """Handle invalid file format error."""
        message = f"Invalid file format for {expected_format.value}"
        if detected_format:
            message += f" (detected: {detected_format})"

        error = ParserError(
            error_type="invalid_format",
            error_category="file",
            severity="error",
            message=message,
            context=context,
            is_blocking=True
        )
        self.errors.append(error)
        return error

    def handle_corrupted_file(
        self,
        file_path: str,
        details: Optional[str] = None,
        context: Optional[str] = None
    ) -> ParserError:
        """Handle corrupted file error."""
        message = f"File appears to be corrupted: {file_path}"
        if details:
            message += f" - {details}"

        error = ParserError(
            error_type="corrupted_file",
            error_category="file",
            severity="error",
            message=message,
            context=context or details,
            is_blocking=True
        )
        self.errors.append(error)
        return error

    def handle_encoding_error(
        self,
        file_path: str,
        encoding_attempted: str,
        details: Optional[str] = None,
        context: Optional[str] = None
    ) -> ParserError:
        """Handle encoding error."""
        message = f"Encoding error when reading file as {encoding_attempted}"
        if details:
            message += f": {details}"

        error = ParserError(
            error_type="encoding_error",
            error_category="file",
            severity="error",
            message=message,
            context=context or f"Attempted encoding: {encoding_attempted}",
            is_blocking=True
        )
        self.errors.append(error)
        return error

    def handle_malformed_csv(
        self,
        row_number: int,
        line_content: Optional[str] = None,
        expected_columns: Optional[int] = None,
        actual_columns: Optional[int] = None,
        context: Optional[str] = None
    ) -> ParserError:
        """Handle malformed CSV row."""
        message = f"Malformed CSV data at row {row_number}"
        if expected_columns and actual_columns:
            message += f" (expected {expected_columns} columns, got {actual_columns})"

        error = ParserError(
            error_type="malformed_csv",
            error_category="content",
            severity="error",
            message=message,
            row_number=row_number,
            raw_value=line_content,
            context=context,
            is_blocking=True
        )
        self.errors.append(error)
        return error

    def handle_excel_read_error(
        self,
        sheet_name: Optional[str] = None,
        row_number: Optional[int] = None,
        column_name: Optional[str] = None,
        details: Optional[str] = None,
        context: Optional[str] = None
    ) -> ParserError:
        """Handle Excel read error."""
        message = "Excel file read error"
        if sheet_name:
            message += f" in sheet '{sheet_name}'"
        if row_number:
            message += f" at row {row_number}"
        if column_name:
            message += f", column '{column_name}'"
        if details:
            message += f": {details}"

        error = ParserError(
            error_type="excel_read_error",
            error_category="content",
            severity="error",
            message=message,
            row_number=row_number,
            column_name=column_name,
            context=context or details,
            is_blocking=True
        )
        self.errors.append(error)
        return error

    def handle_json_structure_error(
        self,
        expected_structure: str,
        actual_structure: Optional[str] = None,
        json_path: Optional[str] = None,
        details: Optional[str] = None,
        context: Optional[str] = None
    ) -> ParserError:
        """Handle JSON structure error."""
        message = f"Invalid JSON structure (expected {expected_structure})"
        if actual_structure:
            message += f", got {actual_structure}"
        if json_path:
            message += f" at path '{json_path}'"
        if details:
            message += f": {details}"

        error = ParserError(
            error_type="json_structure_error",
            error_category="content",
            severity="error",
            message=message,
            context=context or details,
            is_blocking=True
        )
        self.errors.append(error)
        return error

    def handle_memory_error(
        self,
        file_size_mb: float,
        available_mb: Optional[float] = None,
        context: Optional[str] = None
    ) -> ParserError:
        """Handle memory exhaustion error."""
        message = f"Insufficient memory to process file ({file_size_mb:.2f}MB)"
        if available_mb:
            message += f" - only {available_mb:.2f}MB available"

        error = ParserError(
            error_type="memory_error",
            error_category="system",
            severity="error",
            message=message,
            context=context,
            is_blocking=True
        )
        self.errors.append(error)
        return error

    def handle_io_error(
        self,
        operation: str,
        file_path: str,
        details: Optional[str] = None,
        context: Optional[str] = None
    ) -> ParserError:
        """Handle I/O error."""
        message = f"I/O error during {operation} of {file_path}"
        if details:
            message += f": {details}"

        error = ParserError(
            error_type="io_error",
            error_category="system",
            severity="error",
            message=message,
            context=context or details,
            is_blocking=True
        )
        self.errors.append(error)
        return error

    def handle_permission_error(
        self,
        operation: str,
        file_path: str,
        context: Optional[str] = None
    ) -> ParserError:
        """Handle permission error."""
        error = ParserError(
            error_type="permission_error",
            error_category="system",
            severity="error",
            message=f"Permission denied when {operation} {file_path}",
            context=context,
            is_blocking=True
        )
        self.errors.append(error)
        return error

    def handle_validation_error(
        self,
        row_number: Optional[int],
        column_name: Optional[str],
        raw_value: Optional[str],
        expected_type: Optional[DataType],
        actual_value: Optional[str],
        details: Optional[str] = None,
        is_blocking: bool = False,
        context: Optional[str] = None
    ) -> ParserError:
        """Handle data validation error."""
        message = "Validation error"
        if row_number:
            message += f" at row {row_number}"
        if column_name:
            message += f" in column '{column_name}'"
        if expected_type:
            message += f" - expected {expected_type.value}"
        if details:
            message += f": {details}"

        error = ParserError(
            error_type="validation_error",
            error_category="validation",
            severity="error" if is_blocking else "warning",
            message=message,
            row_number=row_number,
            column_name=column_name,
            raw_value=raw_value,
            context=context or details,
            is_blocking=is_blocking
        )

        if is_blocking:
            self.errors.append(error)
        else:
            self.warnings.append(error)

        return error

    def handle_column_error(
        self,
        column_name: str,
        error_type: str,
        details: Optional[str] = None,
        is_blocking: bool = False,
        context: Optional[str] = None
    ) -> ParserError:
        """Handle column-specific error."""
        message = f"Column error: {column_name} - {error_type}"
        if details:
            message += f": {details}"

        error = ParserError(
            error_type="column_error",
            error_category="validation",
            severity="error" if is_blocking else "warning",
            message=message,
            column_name=column_name,
            context=context or details,
            is_blocking=is_blocking
        )

        if is_blocking:
            self.errors.append(error)
        else:
            self.warnings.append(error)

        return error

    def handle_row_error(
        self,
        row_number: int,
        error_type: str,
        row_data: Optional[Dict[str, Any]] = None,
        details: Optional[str] = None,
        is_blocking: bool = False,
        context: Optional[str] = None
    ) -> ParserError:
        """Handle row-specific error."""
        message = f"Row error at line {row_number}: {error_type}"
        if details:
            message += f" - {details}"

        # Convert row data to string for raw_value
        raw_value = str(row_data) if row_data else None

        error = ParserError(
            error_type="row_error",
            error_category="validation",
            severity="error" if is_blocking else "warning",
            message=message,
            row_number=row_number,
            raw_value=raw_value,
            context=context or details,
            is_blocking=is_blocking
        )

        if is_blocking:
            self.errors.append(error)
        else:
            self.warnings.append(error)

        return error

    def handle_general_error(
        self,
        exception: Exception,
        context: Optional[str] = None,
        is_blocking: bool = True
    ) -> ParserError:
        """Handle general parsing error."""
        error = ParserError(
            error_type="general_error",
            error_category="system",
            severity="error",
            message=f"General parsing error: {str(exception)}",
            context=context or traceback.format_exc(),
            is_blocking=is_blocking
        )
        self.errors.append(error)
        return error

    def get_errors(self, severity: Optional[Literal["error", "warning"]] = None) -> List[ParserError]:
        """Get all errors, optionally filtered by severity."""
        if severity == "error":
            return self.errors
        elif severity == "warning":
            return self.warnings
        else:
            return self.errors + self.warnings

    def get_error_count(self) -> int:
        """Get total number of errors."""
        return len(self.errors)

    def get_warning_count(self) -> int:
        """Get total number of warnings."""
        return len(self.warnings)

    def has_blocking_errors(self) -> bool:
        """Check if there are any blocking errors."""
        return any(error.is_blocking for error in self.errors)

    def clear_errors(self) -> None:
        """Clear all errors and warnings."""
        self.errors.clear()
        self.warnings.clear()

    def get_error_summary(self) -> Dict[str, Any]:
        """Get summary of all errors."""
        error_types = {}
        for error in self.errors + self.warnings:
            error_types[error.error_type] = error_types.get(error.error_type, 0) + 1

        return {
            "total_errors": len(self.errors),
            "total_warnings": len(self.warnings),
            "has_blocking_errors": self.has_blocking_errors(),
            "error_types": error_types,
            "errors": [error.model_dump() for error in self.errors],
            "warnings": [error.model_dump() for error in self.warnings]
        }

    @classmethod
    def classify_exception(cls, exception: Exception) -> tuple[str, str]:
        """
        Classify an exception into error type and category.

        Args:
            exception: The exception to classify

        Returns:
            Tuple of (error_type, error_category)
        """
        exception_type = type(exception).__name__
        exception_message = str(exception).lower()

        # File-related errors
        if "FileNotFoundError" == exception_type or "not found" in exception_message:
            return "file_not_found", "file"
        elif "PermissionError" == exception_type or "permission" in exception_message:
            return "permission_error", "system"
        elif "size" in exception_message and "large" in exception_message:
            return "file_too_large", "file"
        elif "corrupt" in exception_message or "invalid" in exception_message:
            return "corrupted_file", "file"

        # Encoding errors
        elif "UnicodeDecodeError" == exception_type or "encoding" in exception_message:
            return "encoding_error", "file"

        # CSV parsing errors
        elif "csv" in exception_message or "delimiter" in exception_message:
            return "malformed_csv", "content"

        # Excel parsing errors
        elif "excel" in exception_message or "openpyxl" in exception_message or "xlrd" in exception_message:
            return "excel_read_error", "content"

        # JSON parsing errors
        elif "json" in exception_message or "JSONDecodeError" == exception_type:
            return "json_structure_error", "content"

        # Memory errors
        elif "MemoryError" == exception_type or "memory" in exception_message:
            return "memory_error", "system"

        # I/O errors
        elif "IOError" == exception_type or "io error" in exception_message:
            return "io_error", "system"

        # Default to general error
        else:
            return "general_error", "system"


# Convenience functions
def handle_exception(
    exception: Exception,
    file_path: Optional[str] = None,
    context: Optional[str] = None
) -> ParserError:
    """
    Convenience function to handle an exception.

    Args:
        exception: The exception to handle
        file_path: Optional file path
        context: Additional context

    Returns:
        ParserError
    """
    handler = ParserErrorHandler()
    error_type, error_category = handler.classify_exception(exception)

    # Create appropriate error based on classification
    if error_type == "file_not_found":
        return handler.handle_file_not_found(file_path or "unknown", context)
    elif error_type == "file_too_large":
        return handler.handle_general_error(exception, context)
    elif error_type == "corrupted_file":
        return handler.handle_corrupted_file(file_path or "unknown", context=context)
    elif error_type == "encoding_error":
        return handler.handle_encoding_error(file_path or "unknown", "utf-8", str(exception), context)
    else:
        return handler.handle_general_error(exception, context)


def create_validation_error(
    row_number: int,
    column_name: str,
    raw_value: str,
    expected_type: DataType,
    details: Optional[str] = None
) -> ParserError:
    """
    Convenience function to create a validation error.

    Args:
        row_number: Row number where error occurred
        column_name: Column name where error occurred
        raw_value: Raw value that caused error
        expected_type: Expected data type
        details: Additional details

    Returns:
        ParserError
    """
    handler = ParserErrorHandler()
    return handler.handle_validation_error(
        row_number=row_number,
        column_name=column_name,
        raw_value=raw_value,
        expected_type=expected_type,
        actual_value=str(raw_value),
        details=details
    )
