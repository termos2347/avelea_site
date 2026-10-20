import os
import sys
import re
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Важно: переменные окружения должны быть выставлены ДО импорта app.*
_tmp_dir = tempfile.mkdtemp(prefix="avelea_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_dir}/test.db"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production-123456"
os.environ["ADMIN_PASSWORD"] = "test-password-123"

# Telegram 2FA выключаем в тестах.
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TELEGRAM_ADMIN_ID"] = ""
os.environ["TELEGRAM_2FA_ENABLED"] = "0"

# В тестах нужен хотя бы один товар (test_product_page, test_sitemap_xml).
os.environ["SEED_DEMO_PRODUCT"] = "1"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text as sa_text

from app.main import app


def extract_csrf(html: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert m, "csrf_token не найден в HTML"
    return m.group(1)


@pytest.fixture
def client():
    """TestClient с изолированной БД.

    Перед каждым тестом дропаем все таблицы — lifespan заново прогонит
    alembic upgrade head и seed, как на боевом сервере.
    """
    from app.core.database import engine, Base
    from app.data import cache

    Base.metadata.drop_all(bind=engine, checkfirst=True)
    with engine.begin() as conn:
        conn.execute(sa_text("DROP TABLE IF EXISTS alembic_version"))

    cache.invalidate()

    with TestClient(app) as c:
        yield c

    cache.invalidate()


@pytest.fixture
def admin_client(client):
    """TestClient с активной админской сессией."""
    r = client.get("/admin/login")
    token = extract_csrf(r.text)
    r = client.post(
        "/admin/login",
        data={"password": os.environ["ADMIN_PASSWORD"], "csrf_token": token},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    assert r.headers["location"] == "/admin/products", r.headers
    return client


@pytest.fixture(autouse=True)
def _reset_shared_state():
    """Чистит in-memory state до и после каждого теста."""
    from app.core.ratelimit import reset_all
    from app.routers.admin import auth as auth_mod

    reset_all()
    with auth_mod._codes_lock:
        auth_mod._pending_codes.clear()

    yield

    reset_all()
    with auth_mod._codes_lock:
        auth_mod._pending_codes.clear()