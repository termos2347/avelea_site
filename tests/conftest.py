import os
import sys
import re
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Важно: переменные окружения должны быть выставлены ДО импорта app.*
_tmp_dir = tempfile.mkdtemp(prefix="avelea_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_dir}/test.db"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["ADMIN_PASSWORD"] = "test-password"

# Telegram 2FA выключаем в тестах. ВАЖНО: не os.environ.pop(), а
# явное присвоение пустой строки — load_dotenv(override=False) не
# перезапишет уже существующие переменные, а значит .env не сможет
# затащить боевые креды в тестовую сессию.
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TELEGRAM_ADMIN_ID"] = ""
os.environ["TELEGRAM_2FA_ENABLED"] = "0"

import pytest
from fastapi.testclient import TestClient

from app.main import app


def extract_csrf(html: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert m, "csrf_token не найден в HTML"
    return m.group(1)


@pytest.fixture
def client():
    """TestClient c запущенным lifespan (миграции + seed)."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_client(client):
    """TestClient с активной админской сессией (2FA выключен в тестах)."""
    r = client.get("/admin/login")
    token = extract_csrf(r.text)
    r = client.post(
        "/admin/login",
        data={"password": "test-password", "csrf_token": token},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    assert r.headers["location"] == "/admin/products", r.headers
    return client


@pytest.fixture(autouse=True)
def _reset_shared_state():
    """Чистит in-memory state до и после каждого теста.

    - rate-limiter (попытки входа)
    - хранилище pending-кодов 2FA
    """
    from app.core.ratelimit import reset_all
    from app.routers.admin import auth as auth_mod

    reset_all()
    with auth_mod._codes_lock:
        auth_mod._pending_codes.clear()

    yield

    reset_all()
    with auth_mod._codes_lock:
        auth_mod._pending_codes.clear()