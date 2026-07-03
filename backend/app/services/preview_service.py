"""Service for generating data preview samples and summary statistics from files."""

import json
import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


def parse_date_safe(val: Any) -> Optional[datetime]:
    """Safely parse dates using common formatting strings."""
    if not val:
        return None
    val_str = str(val).strip()
    
    # Try ISO format
    try:
        if val_str.endswith("Z"):
            val_str = val_str[:-1] + "+00:00"
        return datetime.fromisoformat(val_str)
    except ValueError:
        pass

    # Try common formats
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(val_str, fmt)
        except ValueError:
            continue
            
    return None


def is_numeric_safe(val: Any) -> bool:
    """Check if value can be converted to float."""
    try:
        float(val)
        return True
    except (ValueError, TypeError):
        return False


class StreamingSummaryCalculator:
    """Calculator to compute dataset summary statistics incrementally while streaming."""

    def __init__(self, columns: List[str]):
        """
        Initialize calculator.

        Args:
            columns: List of column names
        """
        self.columns = columns
        self.row_count = 0
        self.missing_counts = {col: 0 for col in columns}
        self.duplicate_count = 0
        self.row_hashes = set()
        
        # Candidate states for type inference
        self.date_candidates = {col: True for col in columns}
        self.numeric_candidates = {col: True for col in columns}
        
        self.min_dates = {}
        self.max_dates = {}
        self.date_missing_counts = {col: 0 for col in columns}

    def process_chunk(self, rows: List[Dict[str, Any]]) -> None:
        """
        Ingest a chunk of rows to update incremental statistics.

        Args:
            rows: List of dicts representing dataset rows
        """
        for row in rows:
            self.row_count += 1

            # Duplicate counting via MD5 hash of stable-serialized row dict
            try:
                row_str = json.dumps(row, sort_keys=True, default=str)
                row_hash = hashlib.md5(row_str.encode('utf-8')).digest()
                if row_hash in self.row_hashes:
                    self.duplicate_count += 1
                else:
                    self.row_hashes.add(row_hash)
            except Exception:
                pass

            # Ingest values for type inference and missing statistics
            for col in self.columns:
                val = row.get(col)
                if val is None or str(val).strip() == "" or str(val).lower() in ("nan", "null", "none"):
                    self.missing_counts[col] += 1
                    if self.date_candidates[col]:
                        self.date_missing_counts[col] += 1
                else:
                    # Update date candidate status
                    if self.date_candidates[col]:
                        parsed_date = parse_date_safe(val)
                        if parsed_date:
                            if col not in self.min_dates or parsed_date < self.min_dates[col]:
                                self.min_dates[col] = parsed_date
                            if col not in self.max_dates or parsed_date > self.max_dates[col]:
                                self.max_dates[col] = parsed_date
                        else:
                            self.date_candidates[col] = False
                            
                    # Update numeric candidate status
                    if self.numeric_candidates[col]:
                        if not is_numeric_safe(val):
                            self.numeric_candidates[col] = False

    def get_summary(
        self,
        file_size: int,
        file_type: str,
        encoding: str = "UTF-8",
        delimiter: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Finalize calculations and return summary statistics dictionary.

        Args:
            file_size: Size of dataset file in bytes
            file_type: Format extension
            encoding: Text encoding
            delimiter: CSV delimiter

        Returns:
            Summary dictionary compatible with DatasetSummary schema
        """
        # Determine column types
        column_types = {}
        for col in self.columns:
            if self.date_candidates[col] and col in self.min_dates:
                column_types[col] = "date"
            elif self.numeric_candidates[col] and self.row_count > self.missing_counts[col]:
                column_types[col] = "numeric"
            else:
                column_types[col] = "string"

        # Build date ranges
        date_ranges = {}
        for col, is_date in self.date_candidates.items():
            if is_date and col in self.min_dates:
                date_ranges[col] = {
                    "start": self.min_dates[col].strftime("%Y-%m-%d"),
                    "end": self.max_dates[col].strftime("%Y-%m-%d"),
                    "missing_count": self.date_missing_counts[col]
                }

        # Clear duplicate counting memory footprint
        self.row_hashes.clear()

        # Human-readable memory usage estimation
        # Rough estimate: ~200 bytes per cell in a pandas-like dictionary memory usage
        cell_count = self.row_count * len(self.columns)
        memory_usage_mb = (cell_count * 200) / (1024 * 1024)
        memory_usage_str = f"{max(memory_usage_mb, 0.1):.1f} MB"

        return {
            "row_count": self.row_count,
            "column_count": len(self.columns),
            "file_size": file_size,
            "file_type": file_type,
            "encoding": encoding,
            "delimiter": delimiter,
            "estimated_memory_usage": memory_usage_str,
            "missing_values": {col: count for col, count in self.missing_counts.items() if count > 0},
            "duplicate_rows": self.duplicate_count,
            "date_ranges": date_ranges,
            "column_types": column_types
        }
