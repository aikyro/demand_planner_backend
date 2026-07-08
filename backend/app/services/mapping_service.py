"""Service for recommending and validating dataset column mappings."""

import logging
from difflib import SequenceMatcher
from typing import Dict, List, Tuple, Optional

from app.schemas.preview import MappingValidationResult

logger = logging.getLogger(__name__)

# Standard target columns in schema
TXN_CANONICAL = ["item_id", "store_id", "date", "quantity", "revenue", "price"]
LOOKUP_CANONICAL = [
    "item_id", "item_name", "category", "brand",
    "store_id", "store_name", "state", "region", "channel"
]

TXN_REQUIRED = ["item_id", "store_id", "date", "quantity"]
LOOKUP_REQUIRED = ["item_id", "store_id"]

# M5 Dataset schemas
CALENDAR_CANONICAL = [
    "date", "wm_yr_wk", "weekday", "wday", "month", "year", "d",
    "event_name_1", "event_type_1", "event_name_2", "event_type_2",
    "snap_CA", "snap_TX", "snap_WI"
]
SELL_PRICES_CANONICAL = ["store_id", "item_id", "wm_yr_wk", "sell_price"]
SALES_CANONICAL = ["id", "item_id", "dept_id", "cat_id", "store_id", "state_id", "d"]

CALENDAR_REQUIRED = ["date", "wm_yr_wk", "d"]
SELL_PRICES_REQUIRED = ["store_id", "item_id", "wm_yr_wk", "sell_price"]
SALES_REQUIRED = ["id", "item_id", "dept_id", "cat_id", "store_id", "state_id", "d"]

# Actuals schemas
ACTUALS_CANONICAL = ["item_id", "date", "actual_value"]
ACTUALS_REQUIRED = ["item_id", "date", "actual_value"]

# Common mapping shortcuts and synonyms
CANONICAL_SYNONYMS = {
    "item_id": ["item_id", "product_id", "sku", "item", "prod", "product", "productid", "itemid", "skunumber", "material"],
    "store_id": ["store_id", "location_id", "store", "loc", "shop", "location", "locationid", "storeid", "branch", "plant"],
    "date": ["dt", "date", "time", "day", "transdate", "salesdate", "period", "timestamp"],
    "quantity": ["qty", "quantity", "units", "sold", "volume", "amount", "salesqty"],
    "actual_quantity": ["actuals", "actual_quantity", "actual_value", "qty", "quantity", "units", "sold", "volume", "actual"],
    "actual_value": ["actual_value", "actuals", "actual_quantity", "quantity", "value", "actual_val"],
    "revenue": ["rev", "revenue", "amount", "sales", "turnover", "total", "value"],
    "price": ["price", "prc", "rate", "cost", "unitprice"]
}


class MappingService:
    """Service to automatically match source headers with canonical schemas and validate mappings."""

    @staticmethod
    def suggest_mappings(
        source_columns: List[str],
        source_type: str = "transaction"
    ) -> Tuple[Dict[str, str], Dict[str, float]]:
        """
        Suggest mapping configuration from user columns to canonical schema.

        Args:
            source_columns: List of columns headers from file upload
            source_type: Type of datasource ('transaction', 'lookup', 'calendar', 'sell_prices', 'sales')

        Returns:
            Tuple of (suggested_mappings dict, confidence_scores dict)
        """
        if source_type == "calendar":
            canonical_columns = CALENDAR_CANONICAL
        elif source_type in ("sell_prices", "sell_price"):
            canonical_columns = SELL_PRICES_CANONICAL
        elif source_type == "sales":
            canonical_columns = SALES_CANONICAL
        elif source_type == "lookup":
            canonical_columns = LOOKUP_CANONICAL
        elif source_type == "actuals":
            canonical_columns = ACTUALS_CANONICAL
        else:
            canonical_columns = TXN_CANONICAL
        
        suggested_mapping = {}
        confidence_scores = {}
        
        # Track already mapped canonical columns to prevent double-mapping
        mapped_canonical = set()
        
        for source_col in source_columns:
            clean_source = source_col.lower().replace("_", "").replace(" ", "").replace("-", "")
            
            best_canonical = None
            best_confidence = 0.0
            
            # 1. Match via exact and substring synonym list
            for canon, synonyms in CANONICAL_SYNONYMS.items():
                if canon not in canonical_columns:
                    continue
                if clean_source == canon.replace("_", ""):
                    best_canonical = canon
                    best_confidence = 1.0
                    break
                for syn in synonyms:
                    if clean_source == syn:
                        best_canonical = canon
                        best_confidence = 1.0
                        break
                    elif syn in clean_source or clean_source in syn:
                        best_canonical = canon
                        best_confidence = 0.9
                if best_confidence == 1.0:
                    break
                    
            # 2. Fuzzy match if synonym list did not yield 1.0 confidence match
            if best_confidence < 1.0:
                for canon in canonical_columns:
                    # Clean canonical column name
                    clean_canon = canon.lower().replace("_", "")
                    
                    # Direct clean match
                    if clean_source == clean_canon:
                        best_canonical = canon
                        best_confidence = 1.0
                        break
                        
                    # Calculate fuzzy similarity
                    ratio = SequenceMatcher(None, clean_source, clean_canon).ratio()
                    
                    # Substring check overrides low fuzzy scores
                    if clean_source in clean_canon or clean_canon in clean_source:
                        ratio = max(ratio, 0.75)
                        
                    if ratio > best_confidence:
                        best_confidence = ratio
                        best_canonical = canon
                        
            # Capping: Accept mapping suggestions only if confidence > 0.6
            if best_canonical and best_confidence >= 0.6 and best_canonical not in mapped_canonical:
                suggested_mapping[source_col] = best_canonical
                confidence_scores[source_col] = round(best_confidence, 2)
                mapped_canonical.add(best_canonical)
                
        return suggested_mapping, confidence_scores

    @staticmethod
    def validate_mappings(
        column_mappings: Dict[str, str],
        source_type: str = "transaction"
    ) -> MappingValidationResult:
        """
        Validate mapped columns against schema requirements.

        Args:
            column_mappings: Mappings supplied by user (user_column -> canonical_column)
            source_type: datasource type ('transaction', 'lookup', 'calendar', 'sell_prices', 'sales')

        Returns:
            MappingValidationResult
        """
        if source_type == "calendar":
            required_fields = CALENDAR_REQUIRED
        elif source_type in ("sell_prices", "sell_price"):
            required_fields = SELL_PRICES_REQUIRED
        elif source_type == "sales":
            required_fields = SALES_REQUIRED
        elif source_type == "lookup":
            required_fields = LOOKUP_REQUIRED
        elif source_type == "actuals":
            required_fields = ACTUALS_REQUIRED
        else:
            required_fields = TXN_REQUIRED
        
        # List of mapped canonical fields
        mapped_canonicals = set(column_mappings.values())
        
        # Identify missing required canonical columns
        missing_required = [field for field in required_fields if field not in mapped_canonicals]
        
        warnings = []
        # Additional warnings
        if source_type == "transaction":
            if "revenue" not in mapped_canonicals:
                warnings.append("Optional column 'revenue' is unmapped. It will be computed as price * quantity.")
            if "price" not in mapped_canonicals and "revenue" not in mapped_canonicals:
                warnings.append("Both optional columns 'price' and 'revenue' are unmapped. At least one is recommended.")
                
        # Detect if any duplicate mappings exist
        seen_canonical = set()
        duplicates = []
        for user_col, canon_col in column_mappings.items():
            if canon_col == "__ignore__":
                continue
            if canon_col in seen_canonical:
                duplicates.append(canon_col)
            seen_canonical.add(canon_col)
            
        if duplicates:
            warnings.append(f"Multiple user columns are mapped to the same canonical columns: {', '.join(set(duplicates))}")
            
        is_valid = len(missing_required) == 0
        
        return MappingValidationResult(
            is_valid=is_valid,
            missing_required=missing_required,
            warnings=warnings
        )
