"""Dependency-light unit tests (no DB needed) for security + tier logic."""
from app.core.security import (
    hash_password, verify_password, create_access_token, decode_token,
)
from app.services.override_service import required_rank
from app.core.deps import ROLE_RANK


def test_password_roundtrip():
    h = hash_password("s3cret")
    assert verify_password("s3cret", h)
    assert not verify_password("wrong", h)


def test_jwt_roundtrip():
    tok, jti = create_access_token("u1", "c1", "admin")
    payload = decode_token(tok)
    assert payload["sub"] == "u1"
    assert payload["company_id"] == "c1"
    assert payload["role"] == "admin"
    assert payload["type"] == "access"
    assert payload["jti"] == jti


def test_approval_tiers():
    assert required_rank(5) == ROLE_RANK["viewer"]    # auto
    assert required_rank(20) == ROLE_RANK["planner"]  # manager
    assert required_rank(40) == ROLE_RANK["admin"]    # manager+director
    assert required_rank(80) == ROLE_RANK["admin"]    # executive


def test_m5_schema_validator():
    from app.validators.schema_validator import SchemaValidator
    
    # 1. Test Sell Prices Schema (Valid case)
    validator = SchemaValidator()
    sell_prices_data = [
        {"store_id": "CA_1", "item_id": "HOBBIES_1_001", "wm_yr_wk": 11325, "sell_price": 9.58}
    ]
    res = validator.validate_schema(sell_prices_data, "sell_prices")
    assert res.is_valid is True
    assert len(res.errors) == 0

    # 2. Test Sell Prices Schema (Missing field warning, non-blocking)
    bad_sell_prices_data = [
        {"store_id": "CA_1", "item_id": "HOBBIES_1_001", "wm_yr_wk": 11325}
    ]
    res_bad = validator.validate_schema(bad_sell_prices_data, "sell_prices")
    # Validate missing required column behaves as warning
    assert len(res_bad.errors) == 1
    assert res_bad.errors[0].column_name == "sell_price"
    assert res_bad.errors[0].is_blocking is False
