import io

import pytest
from PIL import Image

from app.core.config import BASE_DIR
from tests.conftest import extract_csrf


# Папка, куда приложение складывает загруженные картинки.
UPLOADS_DIR = BASE_DIR / "static" / "uploads"


# ============== Вспомогательное ==============

def _png(size=(8, 8), color=(200, 30, 30)) -> bytes:
    """Возвращает байты настоящего PNG."""
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg(size=(8, 8), color=(30, 30, 200)) -> bytes:
    """Возвращает байты настоящего JPEG."""
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


def _first_brand_id() -> str:
    """Берём id первого бренда из БД. В тестовой базе seed создаёт Avelea."""
    from app.core.database import SessionLocal
    from app.data.models import Brand
    with SessionLocal() as db:
        b = db.query(Brand).first()
        return str(b.id) if b else ""


def _first_category_name() -> str:
    """Берём имя первой категории. Seed создаёт «Лицо», «Макияж» и т.д."""
    from app.core.database import SessionLocal
    from app.data.models import Category
    with SessionLocal() as db:
        c = db.query(Category).first()
        return c.name if c else ""


def _payload(**overrides) -> dict:
    """Полный набор полей для POST /admin/products/new."""
    data = {
        "name": "Тестовый товар",
        "price": "999",
        "brand_id": _first_brand_id(),
        "volume_amount": "50",
        "volume_unit": "мл",
        "description": "Описание для теста",
        "categories": [_first_category_name()],
    }
    data.update(overrides)
    return data


def _post_new_product(client, token, **overrides):
    """POST /admin/products/new со всеми обязательными полями."""
    data = _payload(**overrides)
    data["csrf_token"] = token
    png = _png()
    return client.post(
        "/admin/products/new",
        data=data,
        files={"image": ("test.png", png, "image/png")},
        follow_redirects=False,
    )


@pytest.fixture
def clean_uploads():
    """Изолирует static/uploads: чистит папку до и после теста."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    def _clear():
        for f in UPLOADS_DIR.iterdir():
            if f.is_file():
                f.unlink()

    _clear()
    try:
        yield
    finally:
        _clear()


# ============== Авторизация ==============

def test_admin_requires_login(client):
    """Неавторизованный /admin/* встречает обычная 404 как у сайта."""
    r = client.get("/admin/products", follow_redirects=False)
    assert r.status_code == 404

    body = r.text.lower()
    assert "admin" not in body
    assert "админ" not in body
    assert "csrf_token" not in body


def test_login_wrong_password(client):
    r = client.get("/admin/login")
    token = extract_csrf(r.text)
    r = client.post(
        "/admin/login",
        data={"password": "wrong", "csrf_token": token},
    )
    assert r.status_code == 401
    assert "Неверный пароль" in r.text


def test_login_success(client):
    r = client.get("/admin/login")
    token = extract_csrf(r.text)
    r = client.post(
        "/admin/login",
        data={"password": "test-password", "csrf_token": token},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/products"


def test_login_bruteforce_blocked(client):
    """После 5 неудачных попыток — 429, даже если пароль верный."""
    for _ in range(5):
        r = client.get("/admin/login")
        token = extract_csrf(r.text)
        r = client.post(
            "/admin/login",
            data={"password": "wrong", "csrf_token": token},
        )
        assert r.status_code == 401

    r = client.get("/admin/login")
    token = extract_csrf(r.text)
    r = client.post(
        "/admin/login",
        data={"password": "test-password", "csrf_token": token},
    )
    assert r.status_code == 429
    assert "Слишком много попыток" in r.text


def test_login_success_resets_counter(client):
    """После успешного входа счётчик сбрасывается."""
    for _ in range(3):
        r = client.get("/admin/login")
        token = extract_csrf(r.text)
        client.post(
            "/admin/login",
            data={"password": "wrong", "csrf_token": token},
        )

    r = client.get("/admin/login")
    token = extract_csrf(r.text)
    r = client.post(
        "/admin/login",
        data={"password": "test-password", "csrf_token": token},
        follow_redirects=False,
    )
    assert r.status_code == 303

    client.get("/admin/logout")
    r = client.get("/admin/login")
    token = extract_csrf(r.text)
    r = client.post(
        "/admin/login",
        data={"password": "test-password", "csrf_token": token},
        follow_redirects=False,
    )
    assert r.status_code == 303


# ============== CSRF ==============

def test_post_without_csrf_is_forbidden(client):
    r = client.post("/admin/login", data={"password": "test-password"})
    assert r.status_code == 403


def test_post_with_wrong_csrf_is_forbidden(client):
    client.get("/admin/login")
    r = client.post(
        "/admin/login",
        data={"password": "test-password", "csrf_token": "подделка"},
    )
    assert r.status_code == 403


# ============== CRUD ==============

def test_create_category(admin_client):
    r = admin_client.get("/admin/categories")
    token = extract_csrf(r.text)
    r = admin_client.post(
        "/admin/categories/new",
        data={"name": "Тестовая категория", "csrf_token": token},
        follow_redirects=False,
    )
    assert r.status_code == 303

    r = admin_client.get("/admin/categories")
    assert "Тестовая категория" in r.text


def test_create_product(admin_client):
    r = admin_client.get("/admin/products")
    token = extract_csrf(r.text)
    r = _post_new_product(admin_client, token, name="Тестовый товар", price="999")
    assert r.status_code == 303

    r = admin_client.get("/admin/products")
    assert "Тестовый товар" in r.text


# ============== Загрузка изображений ==============

def test_upload_rejects_non_image(admin_client, clean_uploads):
    """Файл с «картинным» расширением, но чужими magic bytes — отклоняется."""
    r = admin_client.get("/admin/products")
    token = extract_csrf(r.text)

    data = _payload(name="Мусорный файл", price="1")
    data["csrf_token"] = token
    r = admin_client.post(
        "/admin/products/new",
        data=data,
        files={"image": ("fake.png", b"MZ\x90\x00 not really a png", "image/png")},
        follow_redirects=False,
    )
    assert r.status_code == 303

    r = admin_client.get("/admin/products", params={"q": "Мусорный"})
    assert "Мусорный файл" in r.text
    assert "/static/uploads/" not in r.text
    assert list(UPLOADS_DIR.iterdir()) == []


def test_upload_rejects_png_magic_with_garbage(admin_client, clean_uploads):
    """PNG-magic + мусор: _sniff_image_ext пропускает, Pillow — отклоняет."""
    r = admin_client.get("/admin/products")
    token = extract_csrf(r.text)

    fake_png = b"\x89PNG\r\n\x1a\n" + b"garbage" * 20
    data = _payload(name="Битый PNG", price="1")
    data["csrf_token"] = token
    r = admin_client.post(
        "/admin/products/new",
        data=data,
        files={"image": ("broken.png", fake_png, "image/png")},
        follow_redirects=False,
    )
    assert r.status_code == 303

    r = admin_client.get("/admin/products", params={"q": "Битый PNG"})
    assert "Битый PNG" in r.text
    assert "/static/uploads/" not in r.text
    assert list(UPLOADS_DIR.iterdir()) == []


def test_upload_valid_png_is_saved(admin_client, clean_uploads):
    """Настоящий PNG сохраняется, URL отдаётся в шаблоне."""
    r = admin_client.get("/admin/products")
    token = extract_csrf(r.text)

    png = _png()
    data = _payload(name="Товар с картинкой", price="500")
    data["csrf_token"] = token
    r = admin_client.post(
        "/admin/products/new",
        data=data,
        files={"image": ("photo.png", png, "image/png")},
        follow_redirects=False,
    )
    assert r.status_code == 303

    r = admin_client.get("/admin/products", params={"q": "Товар с картинкой"})
    assert "Товар с картинкой" in r.text
    assert "/static/uploads/" in r.text

    files = [f.name for f in UPLOADS_DIR.iterdir() if f.is_file()]
    assert len(files) == 1
    assert files[0].endswith(".png")


def test_upload_valid_jpeg_is_saved(admin_client, clean_uploads):
    """Настоящий JPEG тоже сохраняется (проверяем .jpg-расширение)."""
    r = admin_client.get("/admin/products")
    token = extract_csrf(r.text)

    jpg = _jpeg()
    data = _payload(name="Товар с jpg", price="500")
    data["csrf_token"] = token
    r = admin_client.post(
        "/admin/products/new",
        data=data,
        files={"image": ("photo.jpg", jpg, "image/jpeg")},
        follow_redirects=False,
    )
    assert r.status_code == 303

    files = [f.name for f in UPLOADS_DIR.iterdir() if f.is_file()]
    assert len(files) == 1
    assert files[0].endswith(".jpg")


def test_upload_rejects_too_large(admin_client, clean_uploads, monkeypatch):
    """Файл, превышающий MAX_UPLOAD_BYTES, не сохраняется."""
    monkeypatch.setattr("app.main.MAX_UPLOAD_BYTES", 100)

    r = admin_client.get("/admin/products")
    token = extract_csrf(r.text)

    big = b"\x89PNG\r\n\x1a\n" + b"x" * 200
    data = _payload(name="Слишком большой", price="1")
    data["csrf_token"] = token
    r = admin_client.post(
        "/admin/products/new",
        data=data,
        files={"image": ("big.png", big, "image/png")},
        follow_redirects=False,
    )
    assert r.status_code == 303

    r = admin_client.get("/admin/products", params={"q": "Слишком большой"})
    assert "Слишком большой" in r.text
    assert "/static/uploads/" not in r.text
    assert list(UPLOADS_DIR.iterdir()) == []


def test_body_size_limit_returns_413():
    """BodySizeLimitMiddleware отклоняет запрос по Content-Length."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.core.middleware import BodySizeLimitMiddleware

    probe = FastAPI()

    @probe.post("/probe")
    async def probe_endpoint():
        return {"ok": True}

    probe.add_middleware(BodySizeLimitMiddleware, max_bytes=1024)

    with TestClient(probe) as c:
        r = c.post("/probe", content=b"x" * 10)
        assert r.status_code == 200

        r = c.post(
            "/probe",
            content=b"x" * 4096,
            headers={"content-type": "application/octet-stream"},
        )
        assert r.status_code == 413
        assert "слишком большой" in r.text.lower()


# ============== Валидация цены ==============

def test_create_product_rejects_negative_price(admin_client):
    """Отрицательная цена — товар не создаётся, показывается сообщение."""
    r = admin_client.get("/admin/products")
    token = extract_csrf(r.text)

    data = _payload(name="Отрицательный", price="-100")
    data["csrf_token"] = token
    png = _png()
    r = admin_client.post(
        "/admin/products/new",
        data=data,
        files={"image": ("test.png", png, "image/png")},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "не может быть отрицательной" in r.text
    assert "Отрицательный" not in r.text


def test_create_product_accepts_zero_price(admin_client):
    """Ноль — валидная цена (бесплатный товар/подарок)."""
    r = admin_client.get("/admin/products")
    token = extract_csrf(r.text)

    r = _post_new_product(admin_client, token, name="Нулевой", price="0")
    assert r.status_code == 303

    r = admin_client.get("/admin/products", params={"q": "Нулевой"})
    assert "Нулевой" in r.text


def test_update_product_rejects_negative_price(admin_client):
    """Отрицательная цена при редактировании — цена не меняется."""
    from app.core.database import SessionLocal
    from app.data.models import Product

    r = admin_client.get("/admin/products")
    token = extract_csrf(r.text)
    _post_new_product(admin_client, token, name="Целевой", price="500")

    with SessionLocal() as db:
        pid = db.query(Product).filter(Product.name == "Целевой").one().id

    r = admin_client.get(f"/admin/products/{pid}/edit")
    token = extract_csrf(r.text)
    data = _payload(name="Целевой", price="-1")
    data["csrf_token"] = token
    png = _png()
    r = admin_client.post(
        f"/admin/products/{pid}/edit",
        data=data,
        files={"image": ("test.png", png, "image/png")},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "не может быть отрицательной" in r.text

    with SessionLocal() as db:
        p = db.query(Product).filter(Product.id == pid).one()
        assert p.price == 500


# ============== Telegram 2FA ==============

def _enable_2fa(monkeypatch, sink: dict):
    """Активирует 2FA в модуле auth и подменяет отправку в Telegram.

    sink — словарь, куда фейк положит последний «отправленный» код,
    чтобы тест мог его прочитать.
    """
    from app.routers.admin import auth as auth_mod

    monkeypatch.setattr(auth_mod, "TELEGRAM_2FA_ENABLED", True)
    monkeypatch.setattr(auth_mod, "TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setattr(auth_mod, "TELEGRAM_ADMIN_ID", "1")
    monkeypatch.setattr(auth_mod, "TELEGRAM_CODE_TTL", 180)
    monkeypatch.setattr(auth_mod, "TELEGRAM_CODE_MAX_ATTEMPTS", 5)

    async def fake_send(code: str) -> tuple[bool, str]:
        sink["last_code"] = code
        return True, ""

    monkeypatch.setattr(auth_mod, "_send_telegram_code", fake_send)


def test_2fa_disabled_by_default(client):
    """Без настроек Telegram вход идёт в один шаг — как раньше."""
    r = client.get("/admin/login")
    token = extract_csrf(r.text)
    r = client.post(
        "/admin/login",
        data={"password": "test-password", "csrf_token": token},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/products"


def test_2fa_enabled_first_step_redirects_to_code(client, monkeypatch):
    """С включённым 2FA верный пароль не пускает сразу."""
    sink: dict = {}
    _enable_2fa(monkeypatch, sink)

    r = client.get("/admin/login")
    token = extract_csrf(r.text)
    r = client.post(
        "/admin/login",
        data={"password": "test-password", "csrf_token": token},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login/2fa"
    assert "last_code" in sink
    assert len(sink["last_code"]) == 6
    assert sink["last_code"].isdigit()

    # В админку всё ещё нельзя
    r = client.get("/admin/products", follow_redirects=False)
    assert r.status_code == 404


def test_2fa_full_flow(client, monkeypatch):
    """Пароль → код → админка."""
    sink: dict = {}
    _enable_2fa(monkeypatch, sink)

    # Шаг 1: пароль
    r = client.get("/admin/login")
    token = extract_csrf(r.text)
    r = client.post(
        "/admin/login",
        data={"password": "test-password", "csrf_token": token},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login/2fa"

    # Шаг 2: форма кода
    r = client.get("/admin/login/2fa")
    assert r.status_code == 200
    assert "Код из Telegram" in r.text
    code_token = extract_csrf(r.text)

    # Шаг 3: неверный код → 401
    r = client.post(
        "/admin/login/2fa",
        data={"code": "000000", "csrf_token": code_token},
    )
    assert r.status_code == 401
    assert "Неверный код" in r.text

    # Шаг 4: верный код → 303 на /admin/products
    r = client.post(
        "/admin/login/2fa",
        data={"code": sink["last_code"], "csrf_token": code_token},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/products"

    # Админка доступна
    r = client.get("/admin/products")
    assert r.status_code == 200


def test_2fa_wrong_code_too_many_attempts(client, monkeypatch):
    """После N неверных кодов — сброс, надо начинать заново с пароля."""
    sink: dict = {}
    _enable_2fa(monkeypatch, sink)

    from app.routers.admin import auth as auth_mod
    monkeypatch.setattr(auth_mod, "TELEGRAM_CODE_MAX_ATTEMPTS", 3)

    r = client.get("/admin/login")
    token = extract_csrf(r.text)
    client.post(
        "/admin/login",
        data={"password": "test-password", "csrf_token": token},
        follow_redirects=False,
    )

    r = client.get("/admin/login/2fa")
    code_token = extract_csrf(r.text)

    # 3 неверных — все 401
    for _ in range(3):
        r = client.post(
            "/admin/login/2fa",
            data={"code": "000000", "csrf_token": code_token},
        )
        assert r.status_code == 401

    # 4-й раз — сброс, редирект на /admin/login
    r = client.post(
        "/admin/login/2fa",
        data={"code": "000000", "csrf_token": code_token},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login"