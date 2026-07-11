"""安全：pbkdf2 密码哈希/校验（对齐 seed.hash_password 格式）+ JWT 签发/解析。"""
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

from jose import jwt, JWTError

from . import settings

PBKDF2_ITERS = 100_000


def hash_password(password: str) -> str:
    """生成 'pbkdf2_sha256$iters$salt_hex$dk_hex'（与 seed.py 同格式）。"""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERS)
    return f"pbkdf2_sha256${PBKDF2_ITERS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """校验 'pbkdf2_sha256$iters$salt_hex$dk_hex'（seed.py 生成）。"""
    try:
        algo, iters, salt_hex, dk_hex = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    salt = bytes.fromhex(salt_hex)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iters))
    return hmac.compare_digest(dk.hex(), dk_hex)


def create_token(username: str, role_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "role": role_id,
        "iat": now,
        "exp": now + timedelta(hours=settings.JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None
