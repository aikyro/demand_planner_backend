"""File format detection using magic bytes and MIME type validation."""

import os
import mimetypes
from pathlib import Path
from typing import Literal, Optional
from dataclasses import dataclass


# Magic byte signatures for file format detection
MAGIC_BYTES = {
    # CSV files (text-based - no specific magic bytes, but we can check for BOM)
    "csv_utf8_bom": b'\xef\xbb\xbf',
    "csv_utf16_le_bom": b'\xff\xfe',
    "csv_utf16_be_bom": b'\xfe\xff',
    "csv_utf32_le_bom": b'\xff\xfe\x00\x00',
    "csv_utf32_be_bom": b'\x00\x00\xfe\xff',

    # Excel files
    "xlsx": b'PK\x03\x04',  # ZIP signature (xlsx is a ZIP file)
    "xls": b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1',  # OLE2 signature

    # JSON files
    "json_array": b'[',
    "json_object": b'{',
}


# MIME types for validation
MIME_TYPES = {
    "csv": ["text/csv", "application/csv", "text/plain"],
    "xlsx": ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
             "application/zip"],
    "xls": ["application/vnd.ms-excel", "application/excel"],
    "json": ["application/json", "text/json"],
}


@dataclass
class FileDetectionResult:
    """Result of file format detection."""
    format: Optional[Literal["csv", "xlsx", "xls", "json"]]
    mime_type: Optional[str]
    encoding: Optional[str]
    is_valid: bool
    confidence: float
    detected_from: str  # 'extension', 'magic_bytes', 'mime_type'
    error: Optional[str] = None


class FileDetector:
    """Detect file formats using magic bytes and MIME type validation."""

    @staticmethod
    def detect_from_magic_bytes(file_path: str) -> Optional[str]:
        """
        Detect file format using magic bytes.

        Args:
            file_path: Path to the file to detect

        Returns:
            File format string or None if not detected
        """
        try:
            with open(file_path, 'rb') as f:
                header = f.read(16)  # Read first 16 bytes for detection

            # Check for JSON
            if header[0:1] == b'[':
                return "json"
            elif header[0:1] == b'{':
                return "json"

            # Check for CSV BOMs
            if header.startswith(MAGIC_BYTES["csv_utf8_bom"]):
                return "csv"
            elif header.startswith(MAGIC_BYTES["csv_utf16_le_bom"]):
                return "csv"
            elif header.startswith(MAGIC_BYTES["csv_utf16_be_bom"]):
                return "csv"
            elif header.startswith(MAGIC_BYTES["csv_utf32_le_bom"]):
                return "csv"
            elif header.startswith(MAGIC_BYTES["csv_utf32_be_bom"]):
                return "csv"

            # Check for Excel files
            if header.startswith(MAGIC_BYTES["xlsx"]):
                # Need to distinguish xlsx from regular zip
                # by checking file extension
                ext = Path(file_path).suffix.lower()
                if ext in ['.xlsx']:
                    return "xlsx"
                return "xlsx"  # Default to xlsx for zip signatures

            if header.startswith(MAGIC_BYTES["xls"]):
                return "xls"

            return None

        except Exception as e:
            raise ValueError(f"Error reading file for magic byte detection: {str(e)}")

    @staticmethod
    def detect_from_extension(file_path: str) -> Optional[str]:
        """
        Detect file format from file extension.

        Args:
            file_path: Path to the file

        Returns:
            File format string or None if not recognized
        """
        ext = Path(file_path).suffix.lower()

        extension_map = {
            '.csv': 'csv',
            '.xlsx': 'xlsx',
            '.xls': 'xls',
            '.json': 'json',
        }

        return extension_map.get(ext)

    @staticmethod
    def detect_mime_type(file_path: str) -> Optional[str]:
        """
        Detect MIME type from file.

        Args:
            file_path: Path to the file

        Returns:
            MIME type string or None if not detected
        """
        mime_type, _ = mimetypes.guess_type(file_path)
        return mime_type

    @staticmethod
    def detect_encoding(file_path: str) -> str:
        """
        Detect file encoding.

        Args:
            file_path: Path to the file

        Returns:
            Detected encoding string (default: utf-8)
        """
        try:
            import chardet

            with open(file_path, 'rb') as f:
                raw_data = f.read(1024)  # Read first 1KB for encoding detection
                result = chardet.detect(raw_data)

                encoding = result.get('encoding', 'utf-8')
                confidence = result.get('confidence', 0)

                # If confidence is low, default to utf-8
                if confidence < 0.7:
                    return 'utf-8'

                return encoding

        except ImportError:
            # Fallback if chardet is not available
            return 'utf-8'
        except Exception:
            return 'utf-8'

    @classmethod
    def detect_file_format(
        cls,
        file_path: str,
        declared_format: Optional[str] = None
    ) -> FileDetectionResult:
        """
        Comprehensive file format detection using multiple methods.

        Args:
            file_path: Path to the file to detect
            declared_format: Optional format declared by user (from filename or upload)

        Returns:
            FileDetectionResult with detected format and metadata

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file is corrupted or unreadable
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        if not os.path.isfile(file_path):
            raise ValueError(f"Path is not a file: {file_path}")

        # Get file size
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            return FileDetectionResult(
                format=None,
                mime_type=None,
                encoding=None,
                is_valid=False,
                confidence=0.0,
                detected_from='magic_bytes',
                error="File is empty"
            )

        # Detect using multiple methods
        magic_format = cls.detect_from_magic_bytes(file_path)
        extension_format = cls.detect_from_extension(file_path)
        mime_type = cls.detect_mime_type(file_path)
        encoding = cls.detect_encoding(file_path)

        # Determine confidence and final format
        detected_format = None
        confidence = 0.0
        detected_from = 'extension'
        error = None

        # Priority: Magic bytes > Extension > Declared format
        if magic_format:
            detected_format = magic_format
            confidence = 0.95
            detected_from = 'magic_bytes'

            # Verify extension matches
            if extension_format and extension_format != magic_format:
                # Extension doesn't match magic bytes - potential security issue
                error = f"File extension ({extension_format}) doesn't match actual format ({magic_format})"
                confidence = 0.7  # Lower confidence but still valid

        elif extension_format:
            detected_format = extension_format
            confidence = 0.8
            detected_from = 'extension'

        elif declared_format:
            detected_format = declared_format
            confidence = 0.5
            detected_from = 'declared'
            error = "Could not verify format - relying on declared format"

        # Validate MIME type matches detected format
        is_valid = True
        if detected_format and mime_type:
            valid_mimes = MIME_TYPES.get(detected_format, [])
            if mime_type not in valid_mimes:
                is_valid = False
                error = f"MIME type ({mime_type}) doesn't match detected format ({detected_format})"

        # If still no format detected, try to guess from content
        if not detected_format:
            # Try to detect as text file (could be CSV)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    first_line = f.readline()
                    if ',' in first_line or '\t' in first_line:
                        detected_format = 'csv'
                        confidence = 0.6
                        detected_from = 'content_analysis'
            except Exception:
                pass

        return FileDetectionResult(
            format=detected_format,
            mime_type=mime_type,
            encoding=encoding,
            is_valid=is_valid,
            confidence=confidence,
            detected_from=detected_from,
            error=error
        )

    @classmethod
    def validate_file(
        cls,
        file_path: str,
        expected_format: str,
        max_size_mb: int = 1024  # 1GB default
    ) -> tuple[bool, Optional[str]]:
        """
        Validate file against expected format and size constraints.

        Args:
            file_path: Path to the file to validate
            expected_format: Expected file format (csv, xlsx, xls, json)
            max_size_mb: Maximum file size in megabytes

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            # Check file exists
            if not os.path.exists(file_path):
                return False, "File does not exist"

            # Check file size
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            if file_size_mb > max_size_mb:
                return False, f"File size ({file_size_mb:.2f}MB) exceeds maximum ({max_size_mb}MB)"

            # Detect format
            detection_result = cls.detect_file_format(file_path)

            if not detection_result.format:
                return False, f"Could not detect file format: {detection_result.error}"

            # Check format matches expected
            if detection_result.format != expected_format.lower():
                return False, f"File format ({detection_result.format}) doesn't match expected ({expected_format})"

            # Check validation result
            if not detection_result.is_valid:
                return False, detection_result.error or "File validation failed"

            return True, None

        except Exception as e:
            return False, f"Validation error: {str(e)}"

    @classmethod
    def detect_file_from_content(
        cls,
        file_content: bytes,
        declared_format: Optional[str] = None
    ) -> FileDetectionResult:
        """
        Detect file format from file content (bytes) instead of file path.

        Args:
            file_content: File content as bytes
            declared_format: Optional declared format

        Returns:
            FileDetectionResult with detected format and metadata
        """
        import io

        if not file_content:
            return FileDetectionResult(
                format=None,
                mime_type=None,
                encoding=None,
                is_valid=False,
                confidence=0.0,
                detected_from='content',
                error="File content is empty"
            )

        # Detect format from magic bytes in content
        detected_format = None
        confidence = 0.0
        detected_from = 'content'
        error = None

        # Check magic bytes
        header = file_content[:16] if len(file_content) >= 16 else file_content

        # JSON detection
        if header and header[0:1] in [b'[', b'{']:
            detected_format = "json"
            confidence = 0.9
            detected_from = 'magic_bytes'

        # CSV BOM detection
        elif header and header.startswith(MAGIC_BYTES["csv_utf8_bom"]):
            detected_format = "csv"
            confidence = 0.95
            detected_from = 'magic_bytes'

        # Excel detection
        elif header and header.startswith(MAGIC_BYTES["xlsx"]):
            detected_format = "xlsx"
            confidence = 0.95
            detected_from = 'magic_bytes'

        elif header and header.startswith(MAGIC_BYTES["xls"]):
            detected_format = "xls"
            confidence = 0.95
            detected_from = 'magic_bytes'

        # Try to detect as text file (could be CSV)
        elif header:
            try:
                # Try to decode as UTF-8 and check for delimiters
                text_content = file_content[:1024].decode('utf-8', errors='ignore')
                if ',' in text_content or '\t' in text_content or ';' in text_content:
                    detected_format = "csv"
                    confidence = 0.7
                    detected_from = 'content_analysis'
                    error = "Could not verify format - detected as CSV from content structure"
            except Exception:
                error = "Could not analyze file content"

        # Use declared format as fallback
        if not detected_format and declared_format:
            detected_format = declared_format
            confidence = 0.5
            detected_from = 'declared'
            error = "Could not verify format - relying on declared format"

        # Determine MIME type
        mime_type = None
        if detected_format:
            mime_types = MIME_TYPES.get(detected_format, [])
            mime_type = mime_types[0] if mime_types else None

        return FileDetectionResult(
            format=detected_format,
            mime_type=mime_type,
            encoding='utf-8',
            is_valid=detected_format is not None,
            confidence=confidence,
            detected_from=detected_from,
            error=error
        )


def detect_file(file_path: str, declared_format: Optional[str] = None) -> FileDetectionResult:
    """
    Convenience function for file format detection.

    Args:
        file_path: Path to the file
        declared_format: Optional declared format

    Returns:
        FileDetectionResult
    """
    return FileDetector.detect_file_format(file_path, declared_format)


def validate_file(
    file_path: str,
    expected_format: str,
    max_size_mb: int = 1024
) -> tuple[bool, Optional[str]]:
    """
    Convenience function for file validation.

    Args:
        file_path: Path to the file
        expected_format: Expected file format
        max_size_mb: Maximum file size in MB

    Returns:
        Tuple of (is_valid, error_message)
    """
    return FileDetector.validate_file(file_path, expected_format, max_size_mb)

