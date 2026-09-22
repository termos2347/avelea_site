from dotenv import load_dotenv
import os
import sys

load_dotenv()


def _require(name: str, hint: str = "") -> str:
    value = os.getenv(name)
    if not value:
        print(f"❌ Переменная окружения {name} не задана.", file=sys.stderr)
        if hint:
            print(f"   {hint}", file=sys.stderr)
        raise SystemExit(1)
    return value


SECRET_KEY = _require(
    "SECRET_KEY",
    'Сгенерировать: python -c "import secrets; print(secrets.token_urlsafe(32))"',
)

ADMIN_PASSWORD = _require(
    "ADMIN_PASSWORD",
    "Придумайте надёжный пароль для входа в админку.",
)