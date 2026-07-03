"""File handling utilities for temporary file management and cleanup."""

import os
import tempfile
import shutil
from pathlib import Path
from typing import Optional, Union, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class FileHandler:
    """Handle file operations with automatic cleanup and error handling."""

    def __init__(
        self,
        base_dir: Optional[str] = None,
        cleanup_after_hours: int = 24
    ):
        """
        Initialize file handler.

        Args:
            base_dir: Base directory for temporary files (default: system temp)
            cleanup_after_hours: Hours after which to clean up temporary files
        """
        self.base_dir = base_dir or tempfile.gettempdir()
        self.cleanup_after_hours = cleanup_after_hours
        self._temp_files: list[Path] = []

    def create_temp_file(
        self,
        suffix: str = "",
        prefix: str = "upload_",
        content: Optional[bytes] = None
    ) -> Path:
        """
        Create a temporary file.

        Args:
            suffix: File suffix (e.g., '.csv')
            prefix: File prefix (default: 'upload_')
            content: Optional bytes content to write to file

        Returns:
            Path to the created temporary file
        """
        # Create file in base directory
        fd, path = tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=self.base_dir)
        temp_path = Path(path)

        try:
            if content:
                with os.fdopen(fd, 'wb') as f:
                    f.write(content)
            else:
                os.close(fd)

            self._temp_files.append(temp_path)
            logger.info(f"Created temp file: {temp_path}")
            return temp_path

        except Exception as e:
            # Clean up on error
            os.close(fd)
            if temp_path.exists():
                temp_path.unlink()
            raise IOError(f"Failed to create temporary file: {str(e)}")

    def create_temp_dir(
        self,
        suffix: str = "",
        prefix: str = "upload_dir_"
    ) -> Path:
        """
        Create a temporary directory.

        Args:
            suffix: Directory suffix
            prefix: Directory prefix (default: 'upload_dir_')

        Returns:
            Path to the created temporary directory
        """
        temp_path = Path(tempfile.mkdtemp(suffix=suffix, prefix=prefix, dir=self.base_dir))
        self._temp_files.append(temp_path)
        logger.info(f"Created temp directory: {temp_path}")
        return temp_path

    def cleanup_file(self, path: Union[str, Path]) -> bool:
        """
        Clean up a single file or directory.

        Args:
            path: Path to file or directory to clean up

        Returns:
            True if cleanup was successful, False otherwise
        """
        path = Path(path)

        try:
            if not path.exists():
                logger.warning(f"Path does not exist for cleanup: {path}")
                return False

            if path.is_file():
                path.unlink()
                logger.info(f"Cleaned up file: {path}")
            elif path.is_dir():
                shutil.rmtree(path)
                logger.info(f"Cleaned up directory: {path}")

            # Remove from tracking list
            if path in self._temp_files:
                self._temp_files.remove(path)

            return True

        except Exception as e:
            logger.error(f"Failed to clean up {path}: {str(e)}")
            return False

    def cleanup_all(self) -> int:
        """
        Clean up all tracked temporary files and directories.

        Returns:
            Number of files/directories successfully cleaned up
        """
        cleaned_count = 0
        files_to_cleanup = self._temp_files.copy()

        for path in files_to_cleanup:
            if self.cleanup_file(path):
                cleaned_count += 1

        self._temp_files.clear()
        logger.info(f"Cleaned up {cleaned_count} temporary items")
        return cleaned_count

    def cleanup_old_files(self, base_path: Optional[Path] = None) -> int:
        """
        Clean up old temporary files older than cleanup_after_hours.

        Args:
            base_path: Base path to search for old files (default: self.base_dir)

        Returns:
            Number of files cleaned up
        """
        base_path = base_path or Path(self.base_dir)
        cutoff_time = datetime.now() - timedelta(hours=self.cleanup_after_hours)
        cleaned_count = 0

        try:
            # Look for files matching our temp prefix patterns
            for item in base_path.iterdir():
                # Only clean up files/directories we created
                if not (item.name.startswith("upload_") or item.name.startswith("upload_dir_")):
                    continue

                # Check modification time
                mtime = datetime.fromtimestamp(item.stat().st_mtime)

                if mtime < cutoff_time:
                    if self.cleanup_file(item):
                        cleaned_count += 1

            logger.info(f"Cleaned up {cleaned_count} old files")
            return cleaned_count

        except Exception as e:
            logger.error(f"Error during old file cleanup: {str(e)}")
            return 0

    @contextmanager
    def temp_file_context(
        self,
        suffix: str = "",
        prefix: str = "upload_",
        content: Optional[bytes] = None
    ) -> Iterator[Path]:
        """
        Context manager for automatic temporary file cleanup.

        Args:
            suffix: File suffix
            prefix: File prefix
            content: Optional content to write

        Yields:
            Path to the temporary file
        """
        temp_path = None
        try:
            temp_path = self.create_temp_file(suffix=suffix, prefix=prefix, content=content)
            yield temp_path
        finally:
            if temp_path:
                self.cleanup_file(temp_path)

    def get_file_size_mb(self, path: Union[str, Path]) -> float:
        """
        Get file size in megabytes.

        Args:
            path: Path to file

        Returns:
            File size in MB
        """
        path = Path(path)

        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"File not found: {path}")

        size_bytes = path.stat().st_size
        size_mb = size_bytes / (1024 * 1024)

        return round(size_mb, 2)

    def get_file_size_bytes(self, path: Union[str, Path]) -> int:
        """
        Get file size in bytes.

        Args:
            path: Path to file

        Returns:
            File size in bytes
        """
        path = Path(path)

        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"File not found: {path}")

        return path.stat().st_size

    def safe_copy(
        self,
        src: Union[str, Path],
        dst: Union[str, Path],
        chunk_size: int = 8192
    ) -> Path:
        """
        Safely copy a file in chunks to handle large files.

        Args:
            src: Source file path
            dst: Destination file path
            chunk_size: Size of chunks to copy (default: 8KB)

        Returns:
            Path to the copied file
        """
        src = Path(src)
        dst = Path(dst)

        if not src.exists():
            raise FileNotFoundError(f"Source file not found: {src}")

        # Create destination directory if needed
        dst.parent.mkdir(parents=True, exist_ok=True)

        # Copy file in chunks
        with open(src, 'rb') as f_src, open(dst, 'wb') as f_dst:
            while True:
                chunk = f_src.read(chunk_size)
                if not chunk:
                    break
                f_dst.write(chunk)

        logger.info(f"Copied file from {src} to {dst}")
        return dst

    def sanitize_filename(self, filename: str) -> str:
        """
        Sanitize a filename by removing potentially malicious characters.

        Args:
            filename: Original filename

        Returns:
            Sanitized filename
        """
        # Remove path traversal attempts
        filename = filename.replace("..", "").replace("/", "").replace("\\", "")

        # Remove null bytes
        filename = filename.replace("\x00", "")

        # Keep only safe characters
        allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_ ")
        sanitized = "".join(c for c in filename if c in allowed_chars)

        # Ensure filename is not empty
        if not sanitized:
            sanitized = "unnamed_file"

        return sanitized.strip()

    def validate_path(self, path: Union[str, Path], base_dir: Optional[Path] = None) -> bool:
        """
        Validate that a path doesn't escape the base directory.

        Args:
            path: Path to validate
            base_dir: Base directory (default: self.base_dir)

        Returns:
            True if path is safe, False otherwise
        """
        path = Path(path).resolve()
        base_dir = Path(base_dir or self.base_dir).resolve()

        try:
            # Check if path is relative to base directory
            path.relative_to(base_dir)
            return True
        except ValueError:
            logger.warning(f"Path validation failed - path escapes base: {path}")
            return False


def create_temp_file(
    suffix: str = "",
    prefix: str = "upload_",
    content: Optional[bytes] = None
) -> Path:
    """
    Convenience function to create a temporary file.

    Args:
        suffix: File suffix
        prefix: File prefix
        content: Optional content to write

    Returns:
        Path to the temporary file
    """
    handler = FileHandler()
    return handler.create_temp_file(suffix=suffix, prefix=prefix, content=content)


def cleanup_temp_file(path: Union[str, Path]) -> bool:
    """
    Convenience function to clean up a temporary file.

    Args:
        path: Path to file to clean up

    Returns:
        True if cleanup was successful
    """
    handler = FileHandler()
    return handler.cleanup_file(path)


def get_file_size_mb(path: Union[str, Path]) -> float:
    """
    Convenience function to get file size in MB.

    Args:
        path: Path to file

    Returns:
        File size in MB
    """
    handler = FileHandler()
    return handler.get_file_size_mb(path)


def get_file_size_bytes(path: Union[str, Path]) -> int:
    """
    Convenience function to get file size in bytes.

    Args:
        path: Path to file

    Returns:
        File size in bytes
    """
    handler = FileHandler()
    return handler.get_file_size_bytes(path)


def sanitize_filename(filename: str) -> str:
    """
    Convenience function to sanitize a filename.

    Args:
        filename: Original filename

    Returns:
        Sanitized filename
    """
    handler = FileHandler()
    return handler.sanitize_filename(filename)
