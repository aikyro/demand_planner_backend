"""Comprehensive tests for file parser components."""

import pytest
import json
import tempfile
import os
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

import pandas as pd

from app.services.file_detector import FileDetector, detect_file, validate_file
from app.services.file_parser import FileParser, parse_file, validate_file as validate_parse
from app.services.parser_error_handler import ParserErrorHandler, handle_exception
from app.schemas.files import FileType, DataType, ParsingStage
from app.utils.file_utils import FileHandler, sanitize_filename, get_file_size_mb


class TestFileDetector:
    """Test file format detection service."""

    @pytest.fixture
    def sample_csv_file(self):
        """Create a sample CSV file for testing."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write('name,age,city\n')
            f.write('Alice,30,New York\n')
            f.write('Bob,25,Los Angeles\n')
            temp_path = f.name

        yield temp_path
        os.unlink(temp_path)

    @pytest.fixture
    def sample_json_file(self):
        """Create a sample JSON file for testing."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump([
                {"name": "Alice", "age": 30},
                {"name": "Bob", "age": 25}
            ], f)
            temp_path = f.name

        yield temp_path
        os.unlink(temp_path)

    @pytest.fixture
    def empty_file(self):
        """Create an empty file for testing."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            temp_path = f.name

        yield temp_path
        os.unlink(temp_path)

    def test_detect_csv_format(self, sample_csv_file):
        """Test CSV format detection."""
        result = FileDetector.detect_file_format(sample_csv_file)

        assert result.format == 'csv'
        assert result.is_valid
        assert result.confidence > 0.7
        assert result.mime_type in ['text/csv', 'text/plain', None]

    def test_detect_json_format(self, sample_json_file):
        """Test JSON format detection."""
        result = FileDetector.detect_file_format(sample_json_file)

        assert result.format == 'json'
        assert result.is_valid
        assert result.confidence > 0.7

    def test_detect_empty_file(self, empty_file):
        """Test detection of empty file."""
        result = FileDetector.detect_file_format(empty_file)

        assert result.format is None
        assert not result.is_valid
        assert result.error == "File is empty"

    def test_detect_from_extension(self):
        """Test format detection from extension."""
        # Test with mock files
        with tempfile.NamedTemporaryFile(suffix='.csv', delete=True) as f:
            result = FileDetector.detect_from_extension(f.name)
            assert result == 'csv'

        with tempfile.NamedTemporaryFile(suffix='.json', delete=True) as f:
            result = FileDetector.detect_from_extension(f.name)
            assert result == 'json'

    def test_validate_file_success(self, sample_csv_file):
        """Test successful file validation."""
        is_valid, error = FileDetector.validate_file(
            sample_csv_file,
            expected_format='csv',
            max_size_mb=100
        )

        assert is_valid
        assert error is None

    def test_validate_file_wrong_format(self, sample_json_file):
        """Test validation with wrong expected format."""
        is_valid, error = FileDetector.validate_file(
            sample_json_file,
            expected_format='csv',
            max_size_mb=100
        )

        assert not is_valid
        assert "doesn't match expected" in error

    def test_detect_nonexistent_file(self):
        """Test detection of non-existent file."""
        with pytest.raises(FileNotFoundError):
            FileDetector.detect_file_format('/nonexistent/file.csv')

    def test_convenience_functions(self, sample_csv_file):
        """Test convenience functions."""
        # Test detect_file
        result = detect_file(sample_csv_file)
        assert result.format == 'csv'

        # Test validate_file
        is_valid, error = validate_file(sample_csv_file, 'csv')
        assert is_valid
        assert error is None


class TestFileParser:
    """Test file parser service."""

    @pytest.fixture
    def sample_csv_file(self):
        """Create a sample CSV file for testing."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write('name,age,city\n')
            f.write('Alice,30,New York\n')
            f.write('Bob,25,Los Angeles\n')
            f.write('Charlie,35,Chicago\n')
            temp_path = f.name

        yield temp_path
        os.unlink(temp_path)

    @pytest.fixture
    def sample_tsv_file(self):
        """Create a sample TSV file for testing."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write('name\tage\tcity\n')
            f.write('Alice\t30\tNew York\n')
            f.write('Bob\t25\tLos Angeles\n')
            temp_path = f.name

        yield temp_path
        os.unlink(temp_path)

    @pytest.fixture
    def sample_json_file(self):
        """Create a sample JSON file for testing."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump([
                {"name": "Alice", "age": 30, "city": "New York"},
                {"name": "Bob", "age": 25, "city": "Los Angeles"},
                {"name": "Charlie", "age": 35, "city": "Chicago"}
            ], f)
            temp_path = f.name

        yield temp_path
        os.unlink(temp_path)

    def test_parse_csv_success(self, sample_csv_file):
        """Test successful CSV parsing."""
        parser = FileParser()
        result = parser.parse_file(sample_csv_file)

        assert result.success
        assert result.stage == ParsingStage.COMPLETED
        assert result.file_type == FileType.CSV
        assert result.metadata.total_rows == 3
        assert result.metadata.total_columns == 3
        assert result.metadata.column_names == ['name', 'age', 'city']
        assert len(result.sample_data) == 3
        assert result.sample_data[0] == {'name': 'Alice', 'age': 30, 'city': 'New York'}

    def test_parse_tsv_file(self, sample_tsv_file):
        """Test parsing TSV (tab-separated) file."""
        parser = FileParser()
        result = parser.parse_file(sample_tsv_file)

        assert result.success
        assert result.metadata.csv_delimiter == '\t'
        assert result.metadata.total_rows == 2

    def test_parse_json_success(self, sample_json_file):
        """Test successful JSON parsing."""
        parser = FileParser()
        result = parser.parse_file(sample_json_file)

        assert result.success
        assert result.stage == ParsingStage.COMPLETED
        assert result.file_type == FileType.JSON
        assert result.metadata.total_rows == 3
        assert result.metadata.json_structure == 'array_of_objects'
        assert len(result.sample_data) == 3

    def test_validate_csv_file(self, sample_csv_file):
        """Test CSV file validation."""
        parser = FileParser()
        result = parser.validate_file(sample_csv_file, 'csv')

        assert result.is_valid
        assert result.file_format == FileType.CSV
        assert result.size_ok
        assert result.format_detected_ok

    def test_parse_nonexistent_file(self):
        """Test parsing non-existent file."""
        parser = FileParser()
        result = parser.parse_file('/nonexistent/file.csv')

        assert not result.success
        assert result.stage == ParsingStage.FAILED
        assert len(result.errors) > 0

    def test_parse_empty_file(self):
        """Test parsing empty file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            temp_path = f.name

        try:
            parser = FileParser()
            result = parser.parse_file(temp_path)

            assert not result.success
            assert result.metadata.is_empty
        finally:
            os.unlink(temp_path)

    def test_column_type_detection(self, sample_csv_file):
        """Test column type detection."""
        parser = FileParser()
        result = parser.parse_file(sample_csv_file)

        assert result.metadata.column_types is not None
        assert 'name' in result.metadata.column_types
        assert result.metadata.column_types['name'] == DataType.STRING
        assert result.metadata.column_types['age'] == DataType.INTEGER

    def test_convenience_parse_function(self, sample_csv_file):
        """Test convenience parse_file function."""
        result = parse_file(sample_csv_file)

        assert result.success
        assert result.file_type == FileType.CSV


class TestParserErrorHandler:
    """Test parser error handler."""

    def test_handle_file_not_found(self):
        """Test file not found error handling."""
        handler = ParserErrorHandler()
        error = handler.handle_file_not_found('/test/file.csv')

        assert error.error_type == 'file_not_found'
        assert error.error_category == 'file'
        assert error.severity == 'error'
        assert error.is_blocking
        assert 'File not found' in error.message

    def test_handle_invalid_format(self):
        """Test invalid format error handling."""
        handler = ParserErrorHandler()
        error = handler.handle_invalid_format(
            '/test/file.csv',
            'json',
            FileType.CSV
        )

        assert error.error_type == 'invalid_format'
        assert error.is_blocking

    def test_handle_validation_error(self):
        """Test validation error handling."""
        handler = ParserErrorHandler()
        error = handler.handle_validation_error(
            row_number=5,
            column_name='age',
            raw_value='not_a_number',
            expected_type=DataType.INTEGER,
            actual_value='not_a_number'
        )

        assert error.error_type == 'validation_error'
        assert error.row_number == 5
        assert error.column_name == 'age'
        assert not error.is_blocking  # Validation errors are not blocking by default

    def test_error_counting(self):
        """Test error counting."""
        handler = ParserErrorHandler()

        handler.handle_file_not_found('/test1.csv')
        handler.handle_file_not_found('/test2.csv')
        handler.handle_validation_error(1, 'col', 'val', DataType.INTEGER, 'val')

        assert handler.get_error_count() == 2  # Two blocking errors
        assert handler.get_warning_count() == 1  # One warning
        assert handler.has_blocking_errors()

    def test_get_errors_by_severity(self):
        """Test getting errors by severity."""
        handler = ParserErrorHandler()

        handler.handle_file_not_found('/test.csv')
        handler.handle_validation_error(1, 'col', 'val', DataType.INTEGER, 'val')

        errors = handler.get_errors(severity='error')
        warnings = handler.get_errors(severity='warning')

        assert len(errors) == 1
        assert len(warnings) == 1

    def test_clear_errors(self):
        """Test clearing errors."""
        handler = ParserErrorHandler()

        handler.handle_file_not_found('/test.csv')
        handler.clear_errors()

        assert handler.get_error_count() == 0
        assert handler.get_warning_count() == 0

    def test_classify_exception(self):
        """Test exception classification."""
        handler = ParserErrorHandler()

        # Test FileNotFoundError
        error_type, category = handler.classify_exception(FileNotFoundError())
        assert error_type == 'file_not_found'
        assert category == 'file'

        # Test generic exception
        error_type, category = handler.classify_exception(Exception('test'))
        assert error_type == 'general_error'
        assert category == 'system'

    def test_handle_exception_convenience(self):
        """Test convenience exception handling function."""
        error = handle_exception(FileNotFoundError(), '/test.csv')

        assert error.error_type == 'file_not_found'
        assert error.is_blocking


class TestFileUtils:
    """Test file utility functions."""

    def test_sanitize_filename(self):
        """Test filename sanitization."""
        # Test normal filename
        assert sanitize_filename('test.csv') == 'test.csv'

        # Test with special characters
        assert '..' not in sanitize_filename('../test.csv')
        assert '/' not in sanitize_filename('test/file.csv')

        # Test empty result
        result = sanitize_filename('...')
        assert result  # Should not be empty

    def test_file_handler_create_temp_file(self):
        """Test temporary file creation."""
        handler = FileHandler()

        with handler.temp_file_context(suffix='.csv', content=b'test,data\n1,2\n'):
            temp_path = handler._temp_files[-1]
            assert temp_path.exists()
            assert temp_path.suffix == '.csv'

        # File should be cleaned up
        assert not temp_path.exists()

    def test_get_file_size(self):
        """Test file size calculation."""
        # Create a test file
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b'test content')
            temp_path = f.name

        try:
            size_bytes = get_file_size_mb(temp_path) * (1024 * 1024)
            assert size_bytes == len(b'test content')
        finally:
            os.unlink(temp_path)


class TestIntegration:
    """Integration tests for file parser workflow."""

    @pytest.fixture
    def sample_files(self):
        """Create sample files for integration testing."""
        files = {}

        # CSV file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write('product,quantity,price\n')
            f.write('Widget A,100,9.99\n')
            f.write('Widget B,200,14.99\n')
            files['csv'] = f.name

        # JSON file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump([
                {"product": "Widget A", "quantity": 100, "price": 9.99},
                {"product": "Widget B", "quantity": 200, "price": 14.99}
            ], f)
            files['json'] = f.name

        yield files

        # Cleanup
        for path in files.values():
            os.unlink(path)

    def test_full_workflow_csv(self, sample_files):
        """Test complete workflow for CSV file."""
        csv_file = sample_files['csv']

        # Step 1: Validate
        parser = FileParser()
        validation = parser.validate_file(csv_file, 'csv')
        assert validation.is_valid

        # Step 2: Parse
        result = parser.parse_file(csv_file)
        assert result.success
        assert result.metadata.total_rows == 2
        assert result.metadata.total_columns == 3

        # Step 3: Check metadata
        assert result.metadata.has_header
        assert result.metadata.column_names == ['product', 'quantity', 'price']

    def test_full_workflow_json(self, sample_files):
        """Test complete workflow for JSON file."""
        json_file = sample_files['json']

        # Step 1: Validate
        parser = FileParser()
        validation = parser.validate_file(json_file, 'json')
        assert validation.is_valid

        # Step 2: Parse
        result = parser.parse_file(json_file)
        assert result.success
        assert result.metadata.total_rows == 2

        # Step 3: Check sample data
        assert len(result.sample_data) == 2
        assert result.sample_data[0]['product'] == 'Widget A'

    def test_error_recovery_workflow(self):
        """Test workflow with error recovery."""
        parser = FileParser()
        error_handler = ParserErrorHandler()

        # Try to parse non-existent file
        result = parser.parse_file('/nonexistent/file.csv')

        assert not result.success
        assert result.stage == ParsingStage.FAILED

        # Handle the error
        error = error_handler.handle_file_not_found('/nonexistent/file.csv')
        assert error.is_blocking

        # Check error summary
        summary = error_handler.get_error_summary()
        assert summary['total_errors'] == 1
        assert summary['has_blocking_errors']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
