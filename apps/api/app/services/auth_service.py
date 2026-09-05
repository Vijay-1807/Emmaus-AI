import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def now() -> datetime:
    return datetime.now(timezone.utc)


async def get_user_by_email(email: str) -> dict | None:
    db = get_db()
    return await db.users.find_one({"email": email.lower()})


async def get_user_by_id(user_id: str) -> dict | None:
    db = get_db()
    return await db.users.find_one({"_id": user_id})


async def register_user(email: str, password: str, name: str) -> dict:
    db = get_db()
    existing = await get_user_by_email(email)
    if existing:
        raise ValueError("an account with this email already exists")
    user = {
        "_id": uuid.uuid4().hex,
        "email": email.lower(),
        "name": name.strip(),
        "password_hash": hash_password(password),
        "created_at": now(),
    }
    await db.users.insert_one(user)
    return user


async def authenticate_user(email: str, password: str) -> dict:
    user = await get_user_by_email(email)
    if not user or not verify_password(password, user["password_hash"]):
        raise PermissionError("invalid email or password")
    return user


async def _issue_tokens(user: dict) -> dict:
    settings = get_settings()
    access = create_access_token(user["_id"], settings)
    refresh = create_refresh_token(user["_id"], settings)
    payload = decode_token(refresh, "refresh", settings)
    db = get_db()
    await db.refresh_tokens.insert_one(
        {
            "jti": payload["jti"],
            "user_id": user["_id"],
            "expires_at": datetime.fromtimestamp(payload["exp"], timezone.utc),
            "revoked": False,
            "created_at": now(),
        }
    )
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "user": {"id": user["_id"], "email": user["email"], "name": user["name"], "is_anonymous": user.get("is_anonymous", False), "created_at": user["created_at"]},
    }


async def login(email: str, password: str) -> dict:
    user = await authenticate_user(email, password)
    return await _issue_tokens(user)


async def signup(email: str, password: str, name: str) -> dict:
    user = await register_user(email, password, name)
    return await _issue_tokens(user)


async def create_anonymous_session() -> dict:
    db = get_db()
    anon_id = f"anon_{uuid.uuid4().hex}"
    user = {
        "_id": anon_id,
        "email": f"{anon_id}@guest.emmaus.ai",
        "name": "Guest",
        "password_hash": "",
        "is_anonymous": True,
        "created_at": now(),
    }
    await db.users.insert_one(user)
    return await _issue_tokens(user)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def refresh_tokens(refresh_token: str) -> dict:
    settings = get_settings()
    try:
        payload = decode_token(refresh_token, "refresh", settings)
    except jwt.PyJWTError as exc:
        raise PermissionError("invalid refresh token") from exc
    db = get_db()
    stored = await db.refresh_tokens.find_one({"jti": payload["jti"]})
    if not stored or stored.get("revoked"):
        raise PermissionError("refresh token revoked")
    if _as_utc(stored["expires_at"]) < now() + timedelta(seconds=5):
        raise PermissionError("refresh token expired")
    await db.refresh_tokens.update_one({"_id": stored["_id"]}, {"$set": {"revoked": True}})
    user = await get_user_by_id(payload["sub"])
    if not user:
        raise PermissionError("user no longer exists")
    return await _issue_tokens(user)


async def revoke_all_tokens(user_id: str) -> None:
    db = get_db()
    await db.refresh_tokens.update_many({"user_id": user_id}, {"$set": {"revoked": True}})
