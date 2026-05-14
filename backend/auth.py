import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    import bcrypt
except ImportError:  # pragma: no cover - used only when dependency is not installed locally
    bcrypt = None

try:
    import jwt
except ImportError:  # pragma: no cover - used only when dependency is not installed locally
    jwt = None

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .config import load_environment
from .models import Meeting, User


load_environment()

JWT_ALGORITHM = "HS256"
DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "password123"


def jwt_secret_key() -> str:
    return os.getenv("JWT_SECRET_KEY", "dev-only-change-me-but-use-env-in-real-apps")


def jwt_expire_minutes() -> int:
    return int(os.getenv("JWT_EXPIRE_MINUTES", "10080"))


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str) -> str:
    if bcrypt is not None:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return "pbkdf2_sha256$120000$" + base64.urlsafe_b64encode(salt).decode() + "$" + base64.urlsafe_b64encode(digest).decode()


def verify_password(password: str, stored_hash: str) -> bool:
    if stored_hash.startswith("$2") and bcrypt is not None:
        return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))

    try:
        scheme, iterations, salt_text, digest_text = stored_hash.split("$", 3)
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False

    salt = base64.urlsafe_b64decode(salt_text.encode())
    expected = base64.urlsafe_b64decode(digest_text.encode())
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    return hmac.compare_digest(actual, expected)


def base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def fallback_jwt_encode(payload: dict[str, Any], secret: str) -> str:
    header = {"alg": JWT_ALGORITHM, "typ": "JWT"}
    header_text = base64url_encode(json.dumps(header, separators=(",", ":")).encode())
    payload_text = base64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_text}.{payload_text}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_text}.{payload_text}.{base64url_encode(signature)}"


def fallback_jwt_decode(token: str, secret: str) -> dict[str, Any]:
    header_text, payload_text, signature_text = token.split(".")
    signing_input = f"{header_text}.{payload_text}".encode("ascii")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    actual = base64url_decode(signature_text)
    if not hmac.compare_digest(actual, expected):
        raise ValueError("Invalid token signature")

    payload = json.loads(base64url_decode(payload_text))
    if int(payload.get("exp", 0)) < int(datetime.now(timezone.utc).timestamp()):
        raise ValueError("Token expired")
    return payload


def create_access_token(user_id: int) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=jwt_expire_minutes())
    payload = {"sub": str(user_id), "exp": int(expires_at.timestamp())}
    if jwt is not None:
        return jwt.encode(payload, jwt_secret_key(), algorithm=JWT_ALGORITHM)
    return fallback_jwt_encode(payload, jwt_secret_key())


def decode_access_token(token: str) -> int | None:
    try:
        if jwt is not None:
            payload = jwt.decode(token, jwt_secret_key(), algorithms=[JWT_ALGORITHM])
        else:
            payload = fallback_jwt_decode(token, jwt_secret_key())
        return int(payload.get("sub"))
    except Exception:
        return None


def user_to_dict(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "created_at": user.created_at,
    }


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == normalize_email(email)))


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def create_user(db: Session, email: str, password: str) -> User:
    normalized = normalize_email(email)
    if get_user_by_email(db, normalized) is not None:
        raise ValueError("Email is already registered")

    existing_users = db.scalar(select(func.count(User.id))) or 0
    user = User(email=normalized, password_hash=hash_password(password))
    db.add(user)
    db.flush()

    if existing_users == 0:
        db.execute(update(Meeting).where(Meeting.user_id.is_(None)).values(user_id=user.id))

    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(db, email)
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user


def ensure_demo_user(db: Session) -> User:
    existing = get_user_by_email(db, DEMO_EMAIL)
    if existing is not None:
        return existing
    return create_user(db, DEMO_EMAIL, DEMO_PASSWORD)
