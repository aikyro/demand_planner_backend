"""Comprehensive file parsing service for CSV, Excel, and JSON files with streaming support."""

import io
import json
import pandas as pd
from pathlib import Path
from typing import Optional, Dict, List, Any, Iterator, Literal
from datetime import datetime
import logging

# Import our schemas and utilities
from app.schemas.files import (
    FileMetadata, FileType, DataType, ParseResult, ParsingStage,
    FileValidationResult, StreamingChunk, ParsingProgress, ParserError
)
from app.services.file_detector import FileDetector, FileDetectionResult
from app.utils.file_utils import FileHandler, get_file_size_bytes, get_file_size_mb

logger = logging.getLogger(__name__)


class FileParser:
    """Main file parser service supporting CSV, Excel, and JSON formats."""

    def __init__(
        self,
        chunk_size: int = 10000,
        sample_size: int = 10,
        max_memory_mb: int = 500
    ):
        """
        Initialize the file parser.

        Args:
            chunk_size: Number of rows per chunk for streaming
            sample_size: Number of rows to include in sample preview
            max_memory_mb: Maximum memory usage target in MB
        """
        self.chunk_size = chunk_size
        self.sample_size = sample_size
        self.max_memory_mb = max_memory_mb
        self.file_handler = FileHandler()

    def validate_file(
        self,
        file_path: str,
        expected_format: Optional[str] = None
    ) -> FileValidationResult:
        """
        Validate a file before parsing.

        Args:
            file_path: Path to the file to validate
            expected_format: Expected file format (optional)

        Returns:
            FileValidationResult with validation status
        """
        try:
            # Get file size
            file_size_bytes = get_file_size_bytes(file_path)
            file_size_mb = get_file_size_mb(file_path)

            # Detect file format
            detection_result = FileDetector.detect_file_format(
                file_path, declared_format=expected_format
            )

            # Check file format detection
            format_detected_ok = detection_result.format is not None
            format_matches_extension = True
            if expected_format and detection_result.format:
                format_matches_extension = detection_result.format == expected_format.lower()

            # Check size constraints
            size_ok = file_size_bytes < (1024 * 1024 * 1024)  # 1GB limit

            # Check MIME type
            mime_type_ok = detection_result.is_valid
            detected_mime_type = detection_result.mime_type

            # Check encoding
            encoding = detection_result.encoding
            encoding_ok = encoding is not None

            # Check for corruption or empty files
            is_corrupted = detection_result.error is not None and "corrupted" in detection_result.error.lower()
            is_empty = file_size_bytes == 0
            is_readable = not is_corrupted and not is_empty

            # Collect warnings
            warning_messages = []
            if detection_result.error:
                warning_messages.append(detection_result.error)
            if detection_result.confidence < 0.8:
                warning_messages.append(f"Low confidence in format detection ({detection_result.confidence:.2f})")

            return FileValidationResult(
                is_valid=format_detected_ok and size_ok and is_readable,
                file_format=FileType(detection_result.format) if detection_result.format else None,
                confidence=detection_result.confidence,
                file_size_bytes=file_size_bytes,
                file_size_mb=file_size_mb,
                size_ok=size_ok,
                format_detected_ok=format_detected_ok,
                format_matches_extension=format_matches_extension,
                is_corrupted=is_corrupted,
                is_empty=is_empty,
                is_readable=is_readable,
                mime_type_ok=mime_type_ok,
                detected_mime_type=detected_mime_type,
                encoding=encoding,
                encoding_ok=encoding_ok,
                error_message=detection_result.error if not format_detected_ok else None,
                warning_messages=warning_messages
            )

        except Exception as e:
            logger.error(f"Validation error: {str(e)}")
            return FileValidationResult(
                is_valid=False,
                file_format=None,
                confidence=0.0,
                file_size_bytes=0,
                file_size_mb=0.0,
                size_ok=False,
                format_detected_ok=False,
                format_matches_extension=False,
                error_message=f"Validation failed: {str(e)}",
                warning_messages=[]
            )

    def parse_file(
        self,
        file_path: str,
        file_type: Optional[FileType] = None,
        use_streaming: bool = False,
        progress_callback: Optional[callable] = None
    ) -> ParseResult:
        """
        Parse a file and extract its data and metadata.

        Args:
            file_path: Path to the file to parse
            file_type: File type (auto-detected if not provided)
            use_streaming: Whether to use streaming for large files
            progress_callback: Optional callback for progress updates

        Returns:
            ParseResult with parsed data and metadata
        """
        started_at = datetime.now()
        errors = []
        warnings = []

        try:
            # Detect file format if not provided
            if not file_type:
                detection = FileDetector.detect_file_format(file_path)
                if not detection.format:
                    return ParseResult(
                        success=False,
                        stage=ParsingStage.FAILED,
                        message=f"Could not detect file format",
                        file_name=Path(file_path).name,
                        file_type=FileType.CSV,  # Default
                        metadata=self._create_empty_metadata(file_path),
                        errors=[detection.error or "Unknown format"]
                    )
                file_type = FileType(detection.format)

            # Parse based on file type
            if file_type == FileType.CSV:
                return self._parse_csv(
                    file_path, started_at, use_streaming, progress_callback
                )
            elif file_type in [FileType.XLSX, FileType.XLS]:
                return self._parse_excel(
                    file_path, file_type, started_at, use_streaming, progress_callback
                )
            elif file_type == FileType.JSON:
                return self._parse_json(
                    file_path, started_at, use_streaming, progress_callback
                )
            else:
                return ParseResult(
                    success=False,
                    stage=ParsingStage.FAILED,
                    message=f"Unsupported file type: {file_type}",
                    file_name=Path(file_path).name,
                    file_type=file_type,
                    metadata=self._create_empty_metadata(file_path),
                    errors=["Unsupported file type"]
                )

        except Exception as e:
            logger.error(f"Parse error: {str(e)}")
            return ParseResult(
                success=False,
                stage=ParsingStage.FAILED,
                message=f"Parse error: {str(e)}",
                file_name=Path(file_path).name,
                file_type=file_type or FileType.CSV,
                metadata=self._create_empty_metadata(file_path),
                errors=[str(e)],
                completed_at=datetime.now()
            )

    def _parse_csv(
        self,
        file_path: str,
        started_at: datetime,
        use_streaming: bool,
        progress_callback: Optional[callable]
    ) -> ParseResult:
        """Parse CSV file with automatic delimiter detection."""
        errors = []
        warnings = []

        try:
            # Detect delimiter
            delimiter = self._detect_csv_delimiter(file_path)
            if not delimiter:
                delimiter = ','  # Default

            # Read first chunk for metadata and sample
            df_sample = pd.read_csv(
                file_path,
                delimiter=delimiter,
                nrows=self.sample_size + 1,  # +1 for header
                encoding='utf-8',
                on_bad_lines='warn'
            )

            # Check if first row is headers
            has_header = self._detect_header_row(df_sample)

            # Extract metadata
            file_name = Path(file_path).name
            file_size_bytes = get_file_size_bytes(file_path)
            file_size_mb = get_file_size_mb(file_path)

            # Get total rows (estimate for large files)
            if use_streaming or file_size_mb > 50:
                total_rows = self._count_csv_rows(file_path, delimiter)
            else:
                total_rows = len(pd.read_csv(file_path, delimiter=delimiter))

            # Get column names
            if has_header:
                column_names = df_sample.columns.tolist()
            else:
                column_names = [f"column_{i}" for i in range(len(df_sample.columns))]

            # Detect column types
            column_types = self._detect_column_types(df_sample, column_names)

            # Identify date columns
            date_columns = [col for col, dtype in column_types.items() if dtype == DataType.DATE]

            # Create metadata
            metadata = FileMetadata(
                file_name=file_name,
                file_type=FileType.CSV,
                file_size_bytes=file_size_bytes,
                file_size_mb=file_size_mb,
                encoding='utf-8',
                mime_type='text/csv',
                total_rows=total_rows,
                total_columns=len(column_names),
                column_names=column_names,
                column_types=column_types,
                date_columns=date_columns,
                csv_delimiter=delimiter,
                has_header=has_header,
                is_empty=total_rows == 0,
                processing_time_seconds=(datetime.now() - started_at).total_seconds()
            )

            # Prepare sample data
            sample_data = df_sample.head(self.sample_size).to_dict('records')

            return ParseResult(
                success=True,
                stage=ParsingStage.COMPLETED,
                message="CSV file parsed successfully",
                file_name=file_name,
                file_type=FileType.CSV,
                metadata=metadata,
                sample_data=sample_data,
                sample_size=min(self.sample_size, len(sample_data)),
                errors=errors,
                warnings=warnings,
                started_at=started_at,
                completed_at=datetime.now()
            )

        except Exception as e:
            logger.error(f"CSV parse error: {str(e)}")
            return ParseResult(
                success=False,
                stage=ParsingStage.FAILED,
                message=f"CSV parse error: {str(e)}",
                file_name=Path(file_path).name,
                file_type=FileType.CSV,
                metadata=self._create_empty_metadata(file_path),
                errors=[str(e)],
                completed_at=datetime.now()
            )

    def _parse_excel(
        self,
        file_path: str,
        file_type: FileType,
        started_at: datetime,
        use_streaming: bool,
        progress_callback: Optional[callable]
    ) -> ParseResult:
        """Parse Excel file (.xlsx or .xls)."""
        errors = []
        warnings = []

        try:
            # Choose engine based on file type
            engine = 'openpyxl' if file_type == FileType.XLSX else 'xlrd'

            # Read first chunk for metadata
            df_sample = pd.read_excel(
                file_path,
                nrows=self.sample_size + 1,
                engine=engine
            )

            # Get sheet name
            excel_file = pd.ExcelFile(file_path, engine=engine)
            sheet_name = excel_file.sheet_names[0]

            # Extract metadata
            file_name = Path(file_path).name
            file_size_bytes = get_file_size_bytes(file_path)
            file_size_mb = get_file_size_mb(file_path)

            # Get total rows
            if use_streaming or file_size_mb > 50:
                # For large files, use read-only mode to count
                total_rows = self._count_excel_rows(file_path, engine)
            else:
                total_rows = len(pd.read_excel(file_path, engine=engine, sheet_name=sheet_name))

            # Get column names
            column_names = df_sample.columns.tolist()

            # Detect column types
            column_types = self._detect_column_types(df_sample, column_names)

            # Identify date columns
            date_columns = [col for col, dtype in column_types.items() if dtype == DataType.DATE]

            # Create metadata
            metadata = FileMetadata(
                file_name=file_name,
                file_type=file_type,
                file_size_bytes=file_size_bytes,
                file_size_mb=file_size_mb,
                encoding='utf-8',
                total_rows=total_rows,
                total_columns=len(column_names),
                column_names=column_names,
                column_types=column_types,
                date_columns=date_columns,
                excel_sheet_name=sheet_name,
                processing_time_seconds=(datetime.now() - started_at).total_seconds()
            )

            # Prepare sample data
            sample_data = df_sample.head(self.sample_size).to_dict('records')

            return ParseResult(
                success=True,
                stage=ParsingStage.COMPLETED,
                message=f"Excel file parsed successfully",
                file_name=file_name,
                file_type=file_type,
                metadata=metadata,
                sample_data=sample_data,
                sample_size=min(self.sample_size, len(sample_data)),
                errors=errors,
                warnings=warnings,
                started_at=started_at,
                completed_at=datetime.now()
            )

        except Exception as e:
            logger.error(f"Excel parse error: {str(e)}")
            return ParseResult(
                success=False,
                stage=ParsingStage.FAILED,
                message=f"Excel parse error: {str(e)}",
                file_name=Path(file_path).name,
                file_type=file_type,
                metadata=self._create_empty_metadata(file_path),
                errors=[str(e)],
                completed_at=datetime.now()
            )

    def _parse_json(
        self,
        file_path: str,
        started_at: datetime,
        use_streaming: bool,
        progress_callback: Optional[callable]
    ) -> ParseResult:
        """Parse JSON file with structure validation."""
        errors = []
        warnings = []

        try:
            # Read JSON file
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Determine structure
            if isinstance(data, list):
                if len(data) > 0 and isinstance(data[0], dict):
                    json_structure = "array_of_objects"
                    df_sample = pd.DataFrame(data[:self.sample_size])
                else:
                    json_structure = "flat_array"
                    return ParseResult(
                        success=False,
                        stage=ParsingStage.FAILED,
                        message="JSON structure not supported (flat array)",
                        file_name=Path(file_path).name,
                        file_type=FileType.JSON,
                        metadata=self._create_empty_metadata(file_path),
                        errors=["JSON structure not supported - expected array of objects"]
                    )
            elif isinstance(data, dict):
                json_structure = "object"
                # Try to find a list in the object
                list_key = None
                for key, value in data.items():
                    if isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict):
                        list_key = key
                        break

                if list_key:
                    df_sample = pd.DataFrame(data[list_key][:self.sample_size])
                    json_structure = f"object_with_{list_key}"
                else:
                    return ParseResult(
                        success=False,
                        stage=ParsingStage.FAILED,
                        message="JSON structure not supported (object without array)",
                        file_name=Path(file_path).name,
                        file_type=FileType.JSON,
                        metadata=self._create_empty_metadata(file_path),
                        errors=["JSON structure not supported - could not find data array"]
                    )
            else:
                return ParseResult(
                    success=False,
                    stage=ParsingStage.FAILED,
                    message="JSON structure not supported",
                    file_name=Path(file_path).name,
                    file_type=FileType.JSON,
                    metadata=self._create_empty_metadata(file_path),
                    errors=["JSON structure not supported"]
                )

            # Extract metadata
            file_name = Path(file_path).name
            file_size_bytes = get_file_size_bytes(file_path)
            file_size_mb = get_file_size_mb(file_path)

            # Get total rows
            if isinstance(data, list):
                total_rows = len(data)
            else:
                total_rows = len(data.get(list_key, []))

            # Get column names
            column_names = df_sample.columns.tolist()

            # Detect column types
            column_types = self._detect_column_types(df_sample, column_names)

            # Identify date columns
            date_columns = [col for col, dtype in column_types.items() if dtype == DataType.DATE]

            # Create metadata
            metadata = FileMetadata(
                file_name=file_name,
                file_type=FileType.JSON,
                file_size_bytes=file_size_bytes,
                file_size_mb=file_size_mb,
                encoding='utf-8',
                mime_type='application/json',
                total_rows=total_rows,
                total_columns=len(column_names),
                column_names=column_names,
                column_types=column_types,
                date_columns=date_columns,
                json_structure=json_structure,
                processing_time_seconds=(datetime.now() - started_at).total_seconds()
            )

            # Prepare sample data
            sample_data = df_sample.head(self.sample_size).to_dict('records')

            return ParseResult(
                success=True,
                stage=ParsingStage.COMPLETED,
                message="JSON file parsed successfully",
                file_name=file_name,
                file_type=FileType.JSON,
                metadata=metadata,
                sample_data=sample_data,
                sample_size=min(self.sample_size, len(sample_data)),
                errors=errors,
                warnings=warnings,
                started_at=started_at,
                completed_at=datetime.now()
            )

        except Exception as e:
            logger.error(f"JSON parse error: {str(e)}")
            return ParseResult(
                success=False,
                stage=ParsingStage.FAILED,
                message=f"JSON parse error: {str(e)}",
                file_name=Path(file_path).name,
                file_type=FileType.JSON,
                metadata=self._create_empty_metadata(file_path),
                errors=[str(e)],
                completed_at=datetime.now()
            )

    def stream_file(
        self,
        file_path: str,
        file_type: FileType,
        progress_callback: Optional[callable] = None
    ) -> Iterator[StreamingChunk]:
        """
        Stream a file in chunks for processing large files.

        Args:
            file_path: Path to the file
            file_type: Type of file to stream
            progress_callback: Optional callback for progress updates

        Yields:
            StreamingChunk with data from each chunk
        """
        try:
            if file_type == FileType.CSV:
                yield from self._stream_csv(file_path, progress_callback)
            elif file_type in [FileType.XLSX, FileType.XLS]:
                yield from self._stream_excel(file_path, file_type, progress_callback)
            elif file_type == FileType.JSON:
                yield from self._stream_json(file_path, progress_callback)
            else:
                raise ValueError(f"Unsupported file type for streaming: {file_type}")

        except Exception as e:
            logger.error(f"Streaming error: {str(e)}")
            raise

    def _stream_csv(
        self,
        file_path: str,
        progress_callback: Optional[callable]
    ) -> Iterator[StreamingChunk]:
        """Stream CSV file in chunks."""
        delimiter = self._detect_csv_delimiter(file_path) or ','
        chunk_index = 0

        # First, count total rows for progress tracking
        total_rows = self._count_csv_rows(file_path, delimiter)
        total_chunks = (total_rows // self.chunk_size) + (1 if total_rows % self.chunk_size else 0)

        for chunk in pd.read_csv(file_path, delimiter=delimiter, chunksize=self.chunk_size):
            chunk_index += 1
            start_row = (chunk_index - 1) * self.chunk_size
            end_row = start_row + len(chunk) - 1

            yield StreamingChunk(
                chunk_index=chunk_index,
                total_chunks=total_chunks,
                data=chunk.to_dict('records'),
                row_count=len(chunk),
                start_row=start_row,
                end_row=end_row,
                processed_at=datetime.now()
            )

            if progress_callback:
                progress = (chunk_index / total_chunks) * 100
                progress_callback(progress)

    def _stream_excel(
        self,
        file_path: str,
        file_type: FileType,
        progress_callback: Optional[callable]
    ) -> Iterator[StreamingChunk]:
        """Stream Excel file in chunks."""
        engine = 'openpyxl' if file_type == FileType.XLSX else 'xlrd'

        # Read entire file (Excel streaming is limited)
        df = pd.read_excel(file_path, engine=engine)
        total_rows = len(df)
        total_chunks = (total_rows // self.chunk_size) + (1 if total_rows % self.chunk_size else 0)

        for chunk_index in range(total_chunks):
            start_row = chunk_index * self.chunk_size
            end_row = min(start_row + self.chunk_size, total_rows)
            chunk = df.iloc[start_row:end_row]

            yield StreamingChunk(
                chunk_index=chunk_index + 1,
                total_chunks=total_chunks,
                data=chunk.to_dict('records'),
                row_count=len(chunk),
                start_row=start_row,
                end_row=end_row - 1,
                processed_at=datetime.now()
            )

            if progress_callback:
                progress = ((chunk_index + 1) / total_chunks) * 100
                progress_callback(progress)

    def _stream_json(
        self,
        file_path: str,
        progress_callback: Optional[callable]
    ) -> Iterator[StreamingChunk]:
        """Stream JSON file in chunks."""
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if isinstance(data, list):
            total_rows = len(data)
        else:
            # Find the array in the object
            for key, value in data.items():
                if isinstance(value, list):
                    data = value
                    total_rows = len(data)
                    break
            else:
                total_rows = 0

        total_chunks = (total_rows // self.chunk_size) + (1 if total_rows % self.chunk_size else 0)

        for chunk_index in range(total_chunks):
            start_row = chunk_index * self.chunk_size
            end_row = min(start_row + self.chunk_size, total_rows)
            chunk = data[start_row:end_row]

            yield StreamingChunk(
                chunk_index=chunk_index + 1,
                total_chunks=total_chunks,
                data=chunk,
                row_count=len(chunk),
                start_row=start_row,
                end_row=end_row - 1,
                processed_at=datetime.now()
            )

            if progress_callback:
                progress = ((chunk_index + 1) / total_chunks) * 100
                progress_callback(progress)

    def _detect_csv_delimiter(self, file_path: str) -> Optional[str]:
        """Detect CSV delimiter by analyzing the first few lines."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                first_line = f.readline()

            # Count potential delimiters
            delimiters = {
                ',': first_line.count(','),
                '\t': first_line.count('\t'),
                ';': first_line.count(';'),
                '|': first_line.count('|')
            }

            # Return the most frequent delimiter
            return max(delimiters, key=delimiters.get) if delimiters else ','

        except Exception:
            return ','

    def _count_csv_rows(self, file_path: str, delimiter: str) -> int:
        """Count total rows in CSV file efficiently."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return sum(1 for _ in f)
        except Exception:
            return 0

    def _count_excel_rows(self, file_path: str, engine: str) -> int:
        """Count total rows in Excel file."""
        try:
            df = pd.read_excel(file_path, engine=engine, nrows=None)
            return len(df)
        except Exception:
            return 0

    def _detect_header_row(self, df: pd.DataFrame) -> bool:
        """Detect if first row is header row."""
        # Simple heuristic: check if first row contains strings
        first_row = df.iloc[0]
        string_count = sum(isinstance(val, str) for val in first_row)
        return string_count > len(first_row) / 2

    def _detect_column_types(
        self,
        df: pd.DataFrame,
        column_names: List[str]
    ) -> Dict[str, DataType]:
        """Detect data types for each column."""
        column_types = {}

        for col in column_names:
            if col not in df.columns:
                column_types[col] = DataType.UNKNOWN
                continue

            series = df[col].dropna()

            if len(series) == 0:
                column_types[col] = DataType.UNKNOWN
                continue

            # Try to infer type
            dtype = series.dtype

            if pd.api.types.is_integer_dtype(dtype):
                column_types[col] = DataType.INTEGER
            elif pd.api.types.is_float_dtype(dtype):
                column_types[col] = DataType.FLOAT
            elif pd.api.types.is_bool_dtype(dtype):
                column_types[col] = DataType.BOOLEAN
            elif pd.api.types.is_datetime64_any_dtype(dtype):
                column_types[col] = DataType.DATETIME
            elif dtype == 'object':
                # Check if it's a string or date
                if self._is_date_column(series):
                    column_types[col] = DataType.DATE
                else:
                    column_types[col] = DataType.STRING
            else:
                column_types[col] = DataType.UNKNOWN

        return column_types

    def _is_date_column(self, series: pd.Series) -> bool:
        """Check if a column contains date values."""
        try:
            pd.to_datetime(series, errors='raise')
            return True
        except:
            return False

    def _create_empty_metadata(self, file_path: str) -> FileMetadata:
        """Create empty metadata for failed parses."""
        file_name = Path(file_path).name
        file_size_bytes = get_file_size_bytes(file_path)
        file_size_mb = get_file_size_mb(file_path)

        return FileMetadata(
            file_name=file_name,
            file_type=FileType.CSV,
            file_size_bytes=file_size_bytes,
            file_size_mb=file_size_mb,
            is_empty=file_size_bytes == 0
        )


# Convenience functions for direct usage
def parse_file(
    file_path: str,
    file_type: Optional[FileType] = None,
    use_streaming: bool = False,
    progress_callback: Optional[callable] = None
) -> ParseResult:
    """
    Convenience function to parse a file.

    Args:
        file_path: Path to the file
        file_type: File type (auto-detected if not provided)
        use_streaming: Whether to use streaming
        progress_callback: Optional progress callback

    Returns:
        ParseResult
    """
    parser = FileParser()
    return parser.parse_file(file_path, file_type, use_streaming, progress_callback)


def validate_file(
    file_path: str,
    expected_format: Optional[str] = None
) -> FileValidationResult:
    """
    Convenience function to validate a file.

    Args:
        file_path: Path to the file
        expected_format: Expected format

    Returns:
        FileValidationResult
    """
    parser = FileParser()
    return parser.validate_file(file_path, expected_format)


def stream_file(
    file_path: str,
    file_type: FileType,
    progress_callback: Optional[callable] = None
) -> Iterator[StreamingChunk]:
    """
    Convenience function to stream a file.

    Args:
        file_path: Path to the file
        file_type: Type of file
        progress_callback: Optional progress callback

    Yields:
        StreamingChunk
    """
    parser = FileParser()
    yield from parser.stream_file(file_path, file_type, progress_callback)
