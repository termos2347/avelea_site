import io

import pytest
from PIL import Image

from app.config import BASE_DIR, MAX_UPLOAD_BYTES
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


@pytest.fixture
def clean_uploads():
    """Изолирует static/uploads: чистит папку до и после теста.

    Без этого файлы из предыдущих прогонов накапливаются и мешают
    проверкам вида «файл не должен был сохраниться».
    """
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
    r = client.get("/admin/products", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login"


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


# ============== CSRF ==============

def test_post_without_csrf_is_forbidden(client):
    r = client.post("/admin/login", data={"password": "test-password"})
    assert r.status_code == 403


def test_post_with_wrong_csrf_is_forbidden(client):
    client.get("/admin/login")  # создаём сессию и токен
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
    r = admin_client.post(
        "/admin/products/new",
        data={
            "name": "Тестовый товар",
            "price": "999",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    r = admin_client.get("/admin/products")
    assert "Тестовый товар" in r.text


# ============== Загрузка изображений ==============

def test_upload_rejects_non_image(admin_client, clean_uploads):
    """Файл с «картинным» расширением, но чужими magic bytes — отклоняется."""
    r = admin_client.get("/admin/products")
    token = extract_csrf(r.text)
    r = admin_client.post(
        "/admin/products/new",
        data={
            "name": "Мусорный файл",
            "price": "1",
            "csrf_token": token,
        },
        files={
            "image": ("fake.png", b"MZ\x90\x00 not really a png", "image/png"),
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    r = admin_client.get("/admin/products", params={"q": "Мусорный"})
    assert "Мусорный файл" in r.text
    # Файл не должен был сохраниться — картинка отсутствует.
    assert "/static/uploads/" not in r.text
    # И на диске тоже ничего.
    assert list(UPLOADS_DIR.iterdir()) == []


def test_upload_rejects_png_magic_with_garbage(admin_client, clean_uploads):
    """PNG-magic + мусор: _sniff_image_ext пропускает, Pillow — отклоняет.

    Это ключевая проверка второго барьера: без verify() файл бы лёг
    на диск, а браузер не смог бы его отрисовать.
    """
    r = admin_client.get("/admin/products")
    token = extract_csrf(r.text)

    fake_png = b"\x89PNG\r\n\x1a\n" + b"garbage" * 20
    r = admin_client.post(
        "/admin/products/new",
        data={
            "name": "Битый PNG",
            "price": "1",
            "csrf_token": token,
        },
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
    r = admin_client.post(
        "/admin/products/new",
        data={
            "name": "Товар с картинкой",
            "price": "500",
            "csrf_token": token,
        },
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
    r = admin_client.post(
        "/admin/products/new",
        data={
            "name": "Товар с jpg",
            "price": "500",
            "csrf_token": token,
        },
        files={"image": ("photo.jpg", jpg, "image/jpeg")},
        follow_redirects=False,
    )
    assert r.status_code == 303

    files = [f.name for f in UPLOADS_DIR.iterdir() if f.is_file()]
    assert len(files) == 1
    assert files[0].endswith(".jpg")


def test_upload_rejects_too_large(admin_client, clean_uploads, monkeypatch):
    """Файл, превышающий MAX_UPLOAD_BYTES, не сохраняется.

    Лимит занижаем, чтобы не гонять через сеть мегабайты.
    Патчим именно app.main.MAX_UPLOAD_BYTES — константа уже импортирована
    в модуль, поэтому стандартного monkeypatch.setenv недостаточно.
    """
    monkeypatch.setattr("app.main.MAX_UPLOAD_BYTES", 100)

    r = admin_client.get("/admin/products")
    token = extract_csrf(r.text)

    # 208 байт — больше лимита 100.
    big = b"\x89PNG\r\n\x1a\n" + b"x" * 200
    r = admin_client.post(
        "/admin/products/new",
        data={
            "name": "Слишком большой",
            "price": "1",
            "csrf_token": token,
        },
        files={"image": ("big.png", big, "image/png")},
        follow_redirects=False,
    )
    assert r.status_code == 303

    r = admin_client.get("/admin/products", params={"q": "Слишком большой"})
    assert "Слишком большой" in r.text
    assert "/static/uploads/" not in r.text
    assert list(UPLOADS_DIR.iterdir()) == []


def test_body_size_limit_returns_413():
    """BodySizeLimitMiddleware отклоняет запрос по Content-Length.

    Тестируем middleware изолированно, на отдельном FastAPI-приложении:
    так не нужно гнать через TestClient реальные 6 МБ.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.main import BodySizeLimitMiddleware

    probe = FastAPI()

    @probe.post("/probe")
    async def probe_endpoint():
        return {"ok": True}

    probe.add_middleware(BodySizeLimitMiddleware, max_bytes=1024)

    with TestClient(probe) as c:
        # Маленькое тело проходит.
        r = c.post("/probe", content=b"x" * 10)
        assert r.status_code == 200

        # Большое — отсекается до чтения тела.
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

    r = admin_client.post(
        "/admin/products/new",
        data={
            "name": "Отрицательный",
            "price": "-100",
            "csrf_token": token,
        },
        follow_redirects=True,   # чтобы увидеть flash на /admin/products
    )
    assert r.status_code == 200
    assert "не может быть отрицательной" in r.text
    # Товара в списке быть не должно.
    assert "Отрицательный" not in r.text


def test_create_product_accepts_zero_price(admin_client):
    """Ноль — валидная цена (бесплатный товар/подарок)."""
    r = admin_client.get("/admin/products")
    token = extract_csrf(r.text)

    r = admin_client.post(
        "/admin/products/new",
        data={
            "name": "Нулевой",
            "price": "0",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    r = admin_client.get("/admin/products", params={"q": "Нулевой"})
    assert "Нулевой" in r.text


def test_update_product_rejects_negative_price(admin_client):
    """Отрицательная цена при редактировании — цена не меняется."""
    from app.database import SessionLocal
    from app.models import Product

    # Создаём товар с валидной ценой.
    r = admin_client.get("/admin/products")
    token = extract_csrf(r.text)
    admin_client.post(
        "/admin/products/new",
        data={"name": "Целевой", "price": "500", "csrf_token": token},
        follow_redirects=False,
    )

    # Достаём его id из БД — проще, чем парсить HTML.
    with SessionLocal() as db:
        pid = db.query(Product).filter(Product.name == "Целевой").one().id

    # Пробуем «отредактировать» на отрицательную цену.
    r = admin_client.get(f"/admin/products/{pid}/edit")
    token = extract_csrf(r.text)
    r = admin_client.post(
        f"/admin/products/{pid}/edit",
        data={
            "name": "Целевой",
            "price": "-1",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "не может быть отрицательной" in r.text

    # Цена в БД осталась прежней.
    with SessionLocal() as db:
        p = db.query(Product).filter(Product.id == pid).one()
        assert p.price == 500