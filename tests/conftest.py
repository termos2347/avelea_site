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

# ============================================================
# ВАЖНО: перенаправляем storage в tempdir.
#
# Без этого autouse-уборка удаляла бы файлы из боевых
# static/uploads и static/site — где лежат реальные фото.
# ============================================================
from app.core.config import BASE_DIR
from app.services import storage as _storage

_test_uploads = Path(_tmp_dir) / "uploads"
_test_site = Path(_tmp_dir) / "site"
_test_uploads.mkdir(parents=True, exist_ok=True)
_test_site.mkdir(parents=True, exist_ok=True)

_storage._backend.folder = _test_uploads
_storage._site_backend.folder = _test_site

_REAL_UPLOADS = (BASE_DIR / "static" / "uploads").resolve()
_REAL_SITE = (BASE_DIR / "static" / "site").resolve()


def _assert_safe_to_clear(folder: Path) -> None:
    """Страховка: не даём очистить боевые папки, даже если что-то
    сломалось в redirect'е storage → tempdir.
    """
    resolved = folder.resolve()
    if resolved == _REAL_UPLOADS or resolved == _REAL_SITE:
        raise AssertionError(
            f"SAFETY: попытка очистить боевую папку {resolved}. "
            "Проверь, что redirect storage → tempdir в conftest.py "
            "сработал ДО первого теста."
        )


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
    from app.core.security import reset_all
    from app.routers.admin import auth as auth_mod

    reset_all()
    with auth_mod._codes_lock:
        auth_mod._pending_codes.clear()

    yield

    reset_all()
    with auth_mod._codes_lock:
        auth_mod._pending_codes.clear()


@pytest.fixture(autouse=True)
def _clean_test_storage():
    """Очищает временные папки тестового storage.

    ВАЖНО: НЕ трогает static/uploads и static/site — там боевые фото.
    """
    from app.services.storage import _backend, _site_backend

    def _clear(folder):
        _assert_safe_to_clear(folder)
        if folder.exists():
            for f in folder.iterdir():
                if f.is_file():
                    f.unlink()

    _clear(_backend.folder)
    _clear(_site_backend.folder)
    yield
    _clear(_backend.folder)
    _clear(_site_backend.folder)