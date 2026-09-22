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
    """TestClient с активной админской сессией."""
    r = client.get("/admin/login")
    token = extract_csrf(r.text)
    r = client.post(
        "/admin/login",
        data={"password": "test-password", "csrf_token": token},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    return client