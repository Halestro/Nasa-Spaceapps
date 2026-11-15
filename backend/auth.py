"""Small local account/session helpers for the single-operator prototype deployment."""
import base64
import hashlib
import hmac
import secrets
import time

SESSION_TTL = 12 * 60 * 60


def hash_password(password: str) -> tuple[str, str]:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return base64.urlsafe_b64encode(salt).decode(), base64.urlsafe_b64encode(digest).decode()


def check_password(password: str, salt: str, expected: str) -> bool:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.urlsafe_b64decode(salt), 310_000)
    return hmac.compare_digest(base64.urlsafe_b64encode(digest).decode(), expected)


def create_session(user_id: int, secret: str) -> str:
    payload = f"{user_id}.{int(time.time()) + SESSION_TTL}"
    encoded = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    signature = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def read_session(token: str | None, secret: str) -> int | None:
    if not token or "." not in token:
        return None
    try:
        encoded, signature = token.rsplit(".", 1)
        expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
        user_id, expires = payload.split(".", 1)
        if int(expires) < int(time.time()):
            return None
        return int(user_id)
    except (ValueError, TypeError, UnicodeDecodeError):
        return None
