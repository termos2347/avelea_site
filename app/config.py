import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent  # корень проекта

load_dotenv(BASE_DIR / ".env")


def _require(name: str, hint: str = "") -> str:
    value = os.getenv(name)
    if not value or value == "change-me":
        print(f"❌ Переменная {name} не задана.", file=sys.stderr)
        if hint:
            print(f"   {hint}", file=sys.stderr)
        raise SystemExit(1)
    return value


def _str(name: str, default: str = "") -> str:
    return os.getenv(name) or default


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    v = os.getenv(name)
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        print(f"❌ {name}={v!r} — не число.", file=sys.stderr)
        raise SystemExit(1)


# --- Обязательные секреты ---
SECRET_KEY = _require(
    "SECRET_KEY",
    'Сгенерировать: python -c "import secrets; print(secrets.token_urlsafe(32))"',
)
ADMIN_PASSWORD = _require("ADMIN_PASSWORD")

# --- БД ---
DATABASE_URL = _str("DATABASE_URL") or f"sqlite:///{BASE_DIR / 'instance' / 'shop.db'}"

# --- Uvicorn ---
UVICORN_HOST   = _str("UVICORN_HOST", "127.0.0.1")
UVICORN_PORT   = _int("UVICORN_PORT", 8000)
UVICORN_RELOAD = _bool("UVICORN_RELOAD", default=False)

# --- Сессия ---
SESSION_HTTPS_ONLY = _bool("SESSION_HTTPS_ONLY", default=False)
SESSION_SAME_SITE  = _str("SESSION_SAME_SITE", "lax")
SESSION_MAX_AGE    = _int("SESSION_MAX_AGE", 14 * 24 * 3600)

# --- Загрузки ---
MAX_UPLOAD_MB    = _int("MAX_UPLOAD_MB", 5)
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024