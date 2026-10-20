import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent

load_dotenv(BASE_DIR / ".env")


def _require(name: str, hint: str = "") -> str:
    value = os.getenv(name)
    if not value or value == "change-me":
        print(f"❌ Переменная {name} не задана.", file=sys.stderr)
        if hint:
            print(f"   {hint}", file=sys.stderr)
        raise SystemExit(1)
    return value


def _require_min_length(name: str, value: str, min_len: int, hint: str = "") -> str:
    if len(value) < min_len:
        print(
            f"❌ {name} короче {min_len} символов (сейчас {len(value)}).",
            file=sys.stderr,
        )
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


SECRET_KEY = _require_min_length(
    "SECRET_KEY",
    _require(
        "SECRET_KEY",
        'Сгенерировать: python -c "import secrets; print(secrets.token_urlsafe(32))"',
    ),
    min_len=32,
    hint="Подпись cookie сессии. Минимум 32 символа.",
)

ADMIN_PASSWORD = _require_min_length(
    "ADMIN_PASSWORD",
    _require("ADMIN_PASSWORD"),
    min_len=12,
    hint="Пароль входа в админку. Минимум 12 символов.",
)

DATABASE_URL = _require(
    "DATABASE_URL",
    "Укажите строку подключения к Postgres: "
    "postgresql+psycopg://user:pass@host/dbname",
)

UVICORN_HOST    = _str("UVICORN_HOST", "127.0.0.1")
UVICORN_PORT    = _int("UVICORN_PORT", 8000)
UVICORN_RELOAD  = _bool("UVICORN_RELOAD", default=False)
UVICORN_WORKERS = _int("UVICORN_WORKERS", 1)

SESSION_HTTPS_ONLY = _bool("SESSION_HTTPS_ONLY", default=False)
SESSION_SAME_SITE  = _str("SESSION_SAME_SITE", "lax")
SESSION_MAX_AGE    = _int("SESSION_MAX_AGE", 14 * 24 * 3600)

MAX_UPLOAD_MB    = _int("MAX_UPLOAD_MB", 5)
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

MAX_VIDEO_UPLOAD_MB    = _int("MAX_VIDEO_UPLOAD_MB", 30)
MAX_VIDEO_UPLOAD_BYTES = MAX_VIDEO_UPLOAD_MB * 1024 * 1024

MAX_IMAGE_DIMENSION = _int("MAX_IMAGE_DIMENSION", 1200)

SEED_DEMO_PRODUCT = _bool("SEED_DEMO_PRODUCT", default=False)

STORAGE_BACKEND = _str("STORAGE_BACKEND", "local")

S3_ENDPOINT   = _str("S3_ENDPOINT", "")
S3_BUCKET     = _str("S3_BUCKET", "")
S3_ACCESS_KEY = _str("S3_ACCESS_KEY", "")
S3_SECRET_KEY = _str("S3_SECRET_KEY", "")
S3_PUBLIC_URL = _str("S3_PUBLIC_URL", "")

TELEGRAM_BOT_TOKEN = _str("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ADMIN_ID  = _str("TELEGRAM_ADMIN_ID", "").strip()
TELEGRAM_CODE_TTL = _int("TELEGRAM_CODE_TTL", 180)
TELEGRAM_CODE_MAX_ATTEMPTS = _int("TELEGRAM_CODE_MAX_ATTEMPTS", 5)


def _resolve_2fa_flag() -> bool:
    raw = os.getenv("TELEGRAM_2FA_ENABLED", "").strip().lower()

    if raw in ("1", "true", "yes", "on"):
        explicit: bool | None = True
    elif raw in ("0", "false", "no", "off"):
        explicit = False
    else:
        explicit = None

    has_credentials = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_ADMIN_ID)

    if explicit is True and not has_credentials:
        print(
            "❌ TELEGRAM_2FA_ENABLED=1, но TELEGRAM_BOT_TOKEN или "
            "TELEGRAM_ADMIN_ID не заполнены.",
            file=sys.stderr,
        )
        print(
            "   Заполни оба (см. .env.example) или поставь "
            "TELEGRAM_2FA_ENABLED=0.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if explicit is None:
        return has_credentials
    return explicit


TELEGRAM_2FA_ENABLED = _resolve_2fa_flag()