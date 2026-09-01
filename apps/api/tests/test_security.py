import jwt
import pytest

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip():
    hashed = hash_password("supersecret")
    assert hashed != "supersecret"
    assert verify_password("supersecret", hashed)
    assert not verify_password("wrong", hashed)


def test_access_token_roundtrip():
    settings = get_settings()
    token = create_access_token("user123", settings)
    payload = decode_token(token, "access", settings)
    assert payload["sub"] == "user123"
    assert payload["type"] == "access"


def test_refresh_token_type_mismatch():
    settings = get_settings()
    token = create_refresh_token("user123", settings)
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(token, "access", settings)


def test_tampered_token_rejected():
    settings = get_settings()
    token = create_access_token("user123", settings)
    with pytest.raises(jwt.PyJWTError):
        decode_token(token + "tampered", "access", settings)
