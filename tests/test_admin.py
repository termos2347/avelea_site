import io

import pytest
from PIL import Image

from app.core.config import BASE_DIR
from tests.conftest import extract_csrf


# UPLOADS_DIR и SITE_DIR указывают на временные папки, куда
# тестовый storage перенаправлен в conftest.py.
# Боевые static/uploads/ и static/site/ тесты не трогают.
from app.services.storage import (
    _backend as _storage_backend,
    _site_backend as _site_storage_backend,
)

UPLOADS_DIR = _storage_backend.folder
SITE_DIR = _site_storage_backend.folder


# ============== Вспомогательное ==============

def _png(size=(8, 8), color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg(size=(8, 8), color=(30, 30, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


def _first_brand_id() -> str:
    from app.core.database import SessionLocal
    from app.data.models import Brand
    with SessionLocal() as db:
        b = db.query(Brand).first()
        return str(b.id) if b else ""


def _first_category_name() -> str:
    from app.core.database import SessionLocal
    from app.data.models import Category
    with SessionLocal() as db:
        c = db.query(Category).first()
        return c.name if c else ""


def _payload(**overrides) -> dict:
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
    data = _payload(**overrides)
    data["csrf_token"] = token
    png = _png()
    return client.post(
        "/admin/products/new",
        data=data,
        files={"image_1": ("test.png", png, "image/png")},
        follow_redirects=False,
    )


# ============== Авторизация ==============

def test_admin_requires_login(client):
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
        data={"password": "test-password-123", "csrf_token": token},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/products"


def test_login_bruteforce_blocked(client):
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
        data={"password": "test-password-123", "csrf_token": token},
    )
    assert r.status_code == 429
    assert "Слишком много попыток" in r.text


def test_login_success_resets_counter(client):
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
        data={"password": "test-password-123", "csrf_token": token},
        follow_redirects=False,
    )
    assert r.status_code == 303

    client.post("/admin/logout", follow_redirects=False)

    r = client.get("/admin/login")
    token = extract_csrf(r.text)
    r = client.post(
        "/admin/login",
        data={"password": "test-password-123", "csrf_token": token},
        follow_redirects=False,
    )
    assert r.status_code == 303


# ============== Logout ==============

def test_logout_via_get_does_not_work(admin_client):
    """GET /admin/logout → 405, не выкидывает. Вектор <img> закрыт."""
    r = admin_client.get("/admin/logout", follow_redirects=False)
    assert r.status_code == 405

    # Сессия всё ещё работает
    r = admin_client.get("/admin/products")
    assert r.status_code == 200


def test_logout_via_post_works(admin_client):
    """POST /admin/logout → 303 на login."""
    r = admin_client.post("/admin/logout", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login"

    # Сессия очищена — админка снова 404
    r = admin_client.get("/admin/products", follow_redirects=False)
    assert r.status_code == 404


# ============== CSRF ==============

def test_post_without_csrf_is_forbidden(client):
    """Без csrf_token форма входа рендерится заново с понятной ошибкой."""
    r = client.post("/admin/login", data={"password": "test-password-123"})
    assert r.status_code == 403
    assert "Сессия истекла" in r.text
    assert 'name="password"' in r.text


def test_post_with_wrong_csrf_is_forbidden(client):
    client.get("/admin/login")
    r = client.post(
        "/admin/login",
        data={"password": "test-password-123", "csrf_token": "подделка"},
    )
    assert r.status_code == 403
    assert "Сессия истекла" in r.text


# ============== CRUD товаров ==============

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


def test_delete_category_with_products(admin_client):
    """Удаление категории с товарами — не 500, товар остаётся без категории."""
    from app.core.database import SessionLocal
    from app.data.models import Product, Category

    r = admin_client.get("/admin/categories")
    token = extract_csrf(r.text)
    admin_client.post(
        "/admin/categories/new",
        data={"name": "Удаляемая", "csrf_token": token},
    )

    with SessionLocal() as db:
        cat_id = db.query(Category).filter(Category.name == "Удаляемая").one().id

    r = admin_client.get("/admin/products")
    token = extract_csrf(r.text)
    _post_new_product(admin_client, token, name="Товар в категории", categories=["Удаляемая"])

    with SessionLocal() as db:
        pid = db.query(Product).filter(Product.name == "Товар в категории").one().id

    r = admin_client.get("/admin/categories")
    token = extract_csrf(r.text)
    r = admin_client.post(
        f"/admin/categories/{cat_id}/delete",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert r.status_code == 303

    with SessionLocal() as db:
        p = db.query(Product).filter(Product.id == pid).one()
        assert p.categories == []


# ============== Загрузка изображений товаров ==============

def test_upload_rejects_non_image(admin_client):
    r = admin_client.get("/admin/products")
    token = extract_csrf(r.text)

    data = _payload(name="Мусорный файл", price="1")
    data["csrf_token"] = token
    r = admin_client.post(
        "/admin/products/new",
        data=data,
        files={"image_1": ("fake.png", b"MZ\x90\x00 not really a png", "image/png")},
        follow_redirects=False,
    )
    assert r.status_code == 303

    r = admin_client.get("/admin/products", params={"q": "Мусорный"})
    assert "Мусорный файл" in r.text
    assert "/static/uploads/" not in r.text
    assert list(UPLOADS_DIR.iterdir()) == []


def test_upload_rejects_png_magic_with_garbage(admin_client):
    r = admin_client.get("/admin/products")
    token = extract_csrf(r.text)

    fake_png = b"\x89PNG\r\n\x1a\n" + b"garbage" * 20
    data = _payload(name="Битый PNG", price="1")
    data["csrf_token"] = token
    r = admin_client.post(
        "/admin/products/new",
        data=data,
        files={"image_1": ("broken.png", fake_png, "image/png")},
        follow_redirects=False,
    )
    assert r.status_code == 303

    r = admin_client.get("/admin/products", params={"q": "Битый PNG"})
    assert "Битый PNG" in r.text
    assert "/static/uploads/" not in r.text
    assert list(UPLOADS_DIR.iterdir()) == []


def test_upload_valid_png_is_saved(admin_client):
    r = admin_client.get("/admin/products")
    token = extract_csrf(r.text)

    png = _png()
    data = _payload(name="Товар с картинкой", price="500")
    data["csrf_token"] = token
    r = admin_client.post(
        "/admin/products/new",
        data=data,
        files={"image_1": ("photo.png", png, "image/png")},
        follow_redirects=False,
    )
    assert r.status_code == 303

    r = admin_client.get("/admin/products", params={"q": "Товар с картинкой"})
    assert "Товар с картинкой" in r.text
    assert "/static/uploads/" in r.text

    files = [f.name for f in UPLOADS_DIR.iterdir() if f.is_file()]
    assert len(files) == 1
    assert files[0].endswith(".webp")


def test_upload_valid_jpeg_is_saved(admin_client):
    r = admin_client.get("/admin/products")
    token = extract_csrf(r.text)

    jpg = _jpeg()
    data = _payload(name="Товар с jpg", price="500")
    data["csrf_token"] = token
    r = admin_client.post(
        "/admin/products/new",
        data=data,
        files={"image_1": ("photo.jpg", jpg, "image/jpeg")},
        follow_redirects=False,
    )
    assert r.status_code == 303

    files = [f.name for f in UPLOADS_DIR.iterdir() if f.is_file()]
    assert len(files) == 1
    assert files[0].endswith(".webp")


def test_upload_rejects_too_large(admin_client, monkeypatch):
    monkeypatch.setattr("app.services.storage.MAX_UPLOAD_BYTES", 100)

    r = admin_client.get("/admin/products")
    token = extract_csrf(r.text)

    big = b"\x89PNG\r\n\x1a\n" + b"x" * 200
    data = _payload(name="Слишком большой", price="1")
    data["csrf_token"] = token
    r = admin_client.post(
        "/admin/products/new",
        data=data,
        files={"image_1": ("big.png", big, "image/png")},
        follow_redirects=False,
    )
    assert r.status_code == 303

    r = admin_client.get("/admin/products", params={"q": "Слишком большой"})
    assert "Слишком большой" in r.text
    assert "/static/uploads/" not in r.text
    assert list(UPLOADS_DIR.iterdir()) == []


def test_upload_rejects_decompression_bomb(admin_client, monkeypatch):
    """PNG с огромным числом пикселей (но маленьким файлом) не сохраняется."""
    from PIL import Image as PILImage
    monkeypatch.setattr(PILImage, "MAX_IMAGE_PIXELS", 10)

    r = admin_client.get("/admin/products")
    token = extract_csrf(r.text)

    png = _png(size=(8, 8))  # 64 пикселя > 2*10
    data = _payload(name="Бомба", price="1")
    data["csrf_token"] = token
    r = admin_client.post(
        "/admin/products/new",
        data=data,
        files={"image_1": ("bomb.png", png, "image/png")},
        follow_redirects=False,
    )
    assert r.status_code == 303

    r = admin_client.get("/admin/products", params={"q": "Бомба"})
    assert "Бомба" in r.text
    assert "/static/uploads/" not in r.text
    assert list(UPLOADS_DIR.iterdir()) == []


# ============== Видео (mp4) ==============

def test_upload_mp4_video_saves(admin_client):
    """MP4 с правильными magic bytes сохраняется в static/uploads/."""
    # ftyp на смещении 4, бренд isom на 8-12 — так _sniff_ext определяет .mp4
    fake_mp4 = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2" + b"\x00" * 1000

    r = admin_client.get("/admin/products")
    token = extract_csrf(r.text)

    data = _payload(name="Видео-товар", price="100")
    data["csrf_token"] = token
    r = admin_client.post(
        "/admin/products/new",
        data=data,
        files={"image_1": ("test.mp4", fake_mp4, "video/mp4")},
        follow_redirects=False,
    )
    assert r.status_code == 303

    files = [f.name for f in UPLOADS_DIR.iterdir() if f.is_file()]
    assert len(files) == 1
    assert files[0].endswith(".mp4")


def test_upload_rejects_too_large_video(admin_client, monkeypatch):
    """Видео больше MAX_VIDEO_UPLOAD_BYTES отклоняется, товар создаётся без файла."""
    monkeypatch.setattr("app.services.storage.MAX_VIDEO_UPLOAD_BYTES", 100)

    fake_mp4 = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2" + b"x" * 200

    r = admin_client.get("/admin/products")
    token = extract_csrf(r.text)

    data = _payload(name="Большое видео", price="1")
    data["csrf_token"] = token
    r = admin_client.post(
        "/admin/products/new",
        data=data,
        files={"image_1": ("big.mp4", fake_mp4, "video/mp4")},
        follow_redirects=False,
    )
    assert r.status_code == 303

    r = admin_client.get("/admin/products", params={"q": "Большое видео"})
    assert "Большое видео" in r.text
    assert "/static/uploads/" not in r.text
    assert list(UPLOADS_DIR.iterdir()) == []


def test_body_size_limit_returns_413():
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
    r = admin_client.get("/admin/products")
    token = extract_csrf(r.text)

    data = _payload(name="Отрицательный", price="-100")
    data["csrf_token"] = token
    png = _png()
    r = admin_client.post(
        "/admin/products/new",
        data=data,
        files={"image_1": ("test.png", png, "image/png")},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "не может быть отрицательной" in r.text
    assert "Отрицательный" not in r.text


def test_create_product_rejects_non_numeric_price(admin_client):
    """Нечисловая цена — флеш-сообщение, а не 400 HTML."""
    r = admin_client.get("/admin/products")
    token = extract_csrf(r.text)

    data = _payload(name="Кривая цена", price="дорого")
    data["csrf_token"] = token
    png = _png()
    r = admin_client.post(
        "/admin/products/new",
        data=data,
        files={"image_1": ("test.png", png, "image/png")},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "не число" in r.text
    assert "Кривая цена" not in r.text


def test_create_product_accepts_zero_price(admin_client):
    r = admin_client.get("/admin/products")
    token = extract_csrf(r.text)

    r = _post_new_product(admin_client, token, name="Нулевой", price="0")
    assert r.status_code == 303

    r = admin_client.get("/admin/products", params={"q": "Нулевой"})
    assert "Нулевой" in r.text


def test_update_product_rejects_negative_price(admin_client):
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
        files={"image_1": ("test.png", png, "image/png")},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "не может быть отрицательной" in r.text

    with SessionLocal() as db:
        p = db.query(Product).filter(Product.id == pid).one()
        assert p.price == 500


# ============== Утечка файлов при ошибках БД ==============

def test_create_product_rolls_back_files_on_db_error(admin_client, monkeypatch):
    """Если db.commit() падает — загруженные файлы удаляются с диска."""
    from sqlalchemy.orm import Session

    def boom(self, *args, **kwargs):
        raise __import__("sqlalchemy").exc.SQLAlchemyError("simulated")

    monkeypatch.setattr(Session, "commit", boom, raising=True)

    r = admin_client.get("/admin/products")
    token = extract_csrf(r.text)

    data = _payload(name="Сломанный", price="100")
    data["csrf_token"] = token
    png = _png()
    r = admin_client.post(
        "/admin/products/new",
        data=data,
        files={"image_1": ("test.png", png, "image/png")},
        follow_redirects=False,
    )
    assert r.status_code == 303

    assert list(UPLOADS_DIR.iterdir()) == []


# ============== Варианты ==============

def test_create_product_with_variants_sets_min_price(admin_client):
    """Цена товара = минимальная цена варианта."""
    from app.core.database import SessionLocal
    from app.data.models import Product

    r = admin_client.get("/admin/products")
    token = extract_csrf(r.text)

    data = _payload(name="С вариантами", price="1000")
    data["csrf_token"] = token
    data["variant_volume_amount"] = ["10", "50"]
    data["variant_volume_unit"] = ["мл", "мл"]
    data["variant_price"] = ["500", "1500"]
    png = _png()
    r = admin_client.post(
        "/admin/products/new",
        data=data,
        files={"image_1": ("test.png", png, "image/png")},
        follow_redirects=False,
    )
    assert r.status_code == 303

    with SessionLocal() as db:
        p = db.query(Product).filter(Product.name == "С вариантами").one()
        assert p.price == 500
        assert len(p.variants) == 2


def test_update_product_removing_all_variants_warns(admin_client):
    """Удалили все варианты — flash-сообщение о базовой цене."""
    from app.core.database import SessionLocal
    from app.data.models import Product

    r = admin_client.get("/admin/products")
    token = extract_csrf(r.text)
    data = _payload(name="С вариантами 2", price="1000")
    data["csrf_token"] = token
    data["variant_volume_amount"] = ["10"]
    data["variant_volume_unit"] = ["мл"]
    data["variant_price"] = ["500"]
    png = _png()
    admin_client.post(
        "/admin/products/new",
        data=data,
        files={"image_1": ("test.png", png, "image/png")},
        follow_redirects=False,
    )

    with SessionLocal() as db:
        pid = db.query(Product).filter(Product.name == "С вариантами 2").one().id

    r = admin_client.get(f"/admin/products/{pid}/edit")
    token = extract_csrf(r.text)
    data = _payload(name="С вариантами 2", price="777")
    data["csrf_token"] = token
    png = _png()
    r = admin_client.post(
        f"/admin/products/{pid}/edit",
        data=data,
        files={"image_1": ("test.png", png, "image/png")},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "все варианты удалены" in r.text

    with SessionLocal() as db:
        p = db.query(Product).filter(Product.id == pid).one()
        assert p.price == 777
        assert len(p.variants) == 0


# ============== AJAX-ошибки возвращаются JSON'ом ==============

def test_ajax_csrf_error_returns_json(admin_client):
    """AJAX-запрос с невалидным CSRF — JSON, не HTML."""
    r = admin_client.post(
        "/admin/products/new",
        data={"name": "x", "price": "1", "csrf_token": "подделка"},
        headers={"X-Requested-With": "XMLHttpRequest"},
        follow_redirects=False,
    )
    assert r.status_code == 403
    data = r.json()
    assert data["ok"] is False
    assert "error" in data
    assert "Сессия" in data["error"]


def test_non_ajax_csrf_error_returns_html(admin_client):
    """Без X-Requested-With — обычная HTML-страница 403."""
    r = admin_client.post(
        "/admin/products/new",
        data={"name": "x", "price": "1", "csrf_token": "подделка"},
        follow_redirects=False,
    )
    assert r.status_code == 403
    assert "text/html" in r.headers["content-type"]


def test_ajax_404_returns_json(admin_client):
    """AJAX 404 — JSON, не HTML."""
    r = admin_client.get(
        "/admin/products/999999/edit",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert r.status_code == 404
    data = r.json()
    assert data["ok"] is False


# ============== /admin/site ==============

def test_admin_site_page_renders(admin_client):
    r = admin_client.get("/admin/site")
    assert r.status_code == 200
    assert "site-cms" in r.text or "data-page-slug" in r.text


def test_admin_site_text_save(admin_client):
    """AJAX-сохранение текста. Проверяем значение в БД."""
    from app.core.database import SessionLocal
    from app.data.models import Setting
    from app.data import cache

    r = admin_client.get("/admin/site")
    token = extract_csrf(r.text)

    r = admin_client.post(
        "/admin/site/footer_phone/text",
        data={"value": "+7 999 123 45 67", "csrf_token": token},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["value"] == "+7 999 123 45 67"

    cache.invalidate()
    with SessionLocal() as db:
        s = db.query(Setting).filter(Setting.key == "footer_phone").first()
        assert s.value == "+7 999 123 45 67"


def test_admin_site_text_clear(admin_client):
    """Пустой текст → None в БД → рендерится default из settings.py."""
    from app.core.database import SessionLocal
    from app.data.models import Setting
    from app.data import cache

    r = admin_client.get("/admin/site")
    token = extract_csrf(r.text)

    admin_client.post(
        "/admin/site/footer_phone/text",
        data={"value": "123", "csrf_token": token},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    r = admin_client.post(
        "/admin/site/footer_phone/text",
        data={"value": "", "csrf_token": token},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["value"] == ""

    cache.invalidate()
    with SessionLocal() as db:
        s = db.query(Setting).filter(Setting.key == "footer_phone").first()
        assert s is None or s.value is None


def test_admin_site_image_upload(admin_client):
    """Загрузка картинки → файл на диске + url в JSON."""
    for f in SITE_DIR.iterdir():
        if f.is_file():
            f.unlink()

    r = admin_client.get("/admin/site")
    token = extract_csrf(r.text)

    png = _png()
    r = admin_client.post(
        "/admin/site/home_hero_1_image/image",
        data={"csrf_token": token},
        files={"image": ("hero.png", png, "image/png")},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["url"].startswith("/static/site/")
    assert data["info"]["missing"] is False

    files = [f.name for f in SITE_DIR.iterdir() if f.is_file()]
    assert len(files) == 1


def test_admin_site_image_remove(admin_client):
    """remove=1 → Setting очищается, файл удаляется."""
    from app.core.database import SessionLocal
    from app.data.models import Setting
    from app.data import cache

    for f in SITE_DIR.iterdir():
        if f.is_file():
            f.unlink()

    r = admin_client.get("/admin/site")
    token = extract_csrf(r.text)

    png = _png()
    admin_client.post(
        "/admin/site/home_hero_1_image/image",
        data={"csrf_token": token},
        files={"image": ("hero.png", png, "image/png")},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    r = admin_client.post(
        "/admin/site/home_hero_1_image/image",
        data={"csrf_token": token, "remove": "1"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["removed"] is True

    cache.invalidate()
    with SessionLocal() as db:
        s = db.query(Setting).filter(Setting.key == "home_hero_1_image").first()
        assert s is None or s.value is None

    assert list(SITE_DIR.iterdir()) == []


def test_admin_site_image_rollback_on_db_error(admin_client, monkeypatch):
    """Если db.commit() упал — новый файл удаляется с диска."""
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.orm import Session

    for f in SITE_DIR.iterdir():
        if f.is_file():
            f.unlink()

    r = admin_client.get("/admin/site")
    token = extract_csrf(r.text)

    def boom(self, *args, **kwargs):
        raise SQLAlchemyError("simulated")

    monkeypatch.setattr(Session, "commit", boom, raising=True)

    png = _png()
    r = admin_client.post(
        "/admin/site/home_hero_1_image/image",
        data={"csrf_token": token},
        files={"image": ("hero.png", png, "image/png")},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert r.status_code == 503
    assert r.json()["ok"] is False
    assert list(SITE_DIR.iterdir()) == []


def test_admin_site_text_ajax_csrf_invalid(admin_client):
    """AJAX-запрос с невалидным CSRF → JSON 403, не HTML."""
    r = admin_client.post(
        "/admin/site/footer_phone/text",
        data={"value": "x", "csrf_token": "подделка"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert r.status_code == 403
    assert r.json()["ok"] is False


# ============== /admin/brands ==============

def test_admin_brands_create(admin_client):
    r = admin_client.get("/admin/brands")
    token = extract_csrf(r.text)
    r = admin_client.post(
        "/admin/brands/new",
        data={"name": "TestBrand", "description": "Описание", "csrf_token": token},
        follow_redirects=False,
    )
    assert r.status_code == 303

    r = admin_client.get("/admin/brands")
    assert "TestBrand" in r.text


def test_admin_brands_duplicate(admin_client):
    r = admin_client.get("/admin/brands")
    token = extract_csrf(r.text)
    admin_client.post("/admin/brands/new", data={"name": "Dup", "csrf_token": token})
    r = admin_client.post(
        "/admin/brands/new",
        data={"name": "Dup", "csrf_token": token},
        follow_redirects=True,
    )
    assert "уже существует" in r.text


def test_admin_brands_edit(admin_client):
    from app.core.database import SessionLocal
    from app.data.models import Brand
    from app.data import cache

    r = admin_client.get("/admin/brands")
    token = extract_csrf(r.text)
    admin_client.post("/admin/brands/new", data={"name": "Old", "csrf_token": token})

    cache.invalidate()
    with SessionLocal() as db:
        bid = db.query(Brand).filter(Brand.name == "Old").one().id

    r = admin_client.post(
        f"/admin/brands/{bid}/edit",
        data={"name": "New", "description": "desc", "csrf_token": token},
        follow_redirects=False,
    )
    assert r.status_code == 303

    cache.invalidate()
    with SessionLocal() as db:
        b = db.query(Brand).filter(Brand.id == bid).one()
        assert b.name == "New"
        assert b.description == "desc"


def test_admin_brands_delete_clears_product_brand(admin_client):
    """Удаление бренда — у товаров brand_id становится NULL."""
    from app.core.database import SessionLocal
    from app.data.models import Brand, Product
    from app.data import cache

    r = admin_client.get("/admin/brands")
    token = extract_csrf(r.text)
    admin_client.post("/admin/brands/new", data={"name": "ToDelete", "csrf_token": token})

    cache.invalidate()
    with SessionLocal() as db:
        bid = db.query(Brand).filter(Brand.name == "ToDelete").one().id

    with SessionLocal() as db:
        p = db.query(Product).first()
        if p:
            p.brand_id = bid
            db.commit()
            pid = p.id

    r = admin_client.post(
        f"/admin/brands/{bid}/delete",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert r.status_code == 303

    cache.invalidate()
    with SessionLocal() as db:
        assert db.query(Brand).filter(Brand.id == bid).first() is None
        if p:
            p2 = db.query(Product).filter(Product.id == pid).one()
            assert p2.brand_id is None


# ============== /admin/categories edit ==============

def test_admin_categories_edit(admin_client):
    from app.core.database import SessionLocal
    from app.data.models import Category
    from app.data import cache

    r = admin_client.get("/admin/categories")
    token = extract_csrf(r.text)
    admin_client.post("/admin/categories/new", data={"name": "OldCat", "csrf_token": token})

    cache.invalidate()
    with SessionLocal() as db:
        cid = db.query(Category).filter(Category.name == "OldCat").one().id

    r = admin_client.post(
        f"/admin/categories/{cid}/edit",
        data={"name": "NewCat", "csrf_token": token},
        follow_redirects=False,
    )
    assert r.status_code == 303

    cache.invalidate()
    with SessionLocal() as db:
        c = db.query(Category).filter(Category.id == cid).one()
        assert c.name == "NewCat"


def test_admin_categories_edit_duplicate(admin_client):
    r = admin_client.get("/admin/categories")
    token = extract_csrf(r.text)
    admin_client.post("/admin/categories/new", data={"name": "Cat1", "csrf_token": token})
    admin_client.post("/admin/categories/new", data={"name": "Cat2", "csrf_token": token})

    from app.core.database import SessionLocal
    from app.data.models import Category
    from app.data import cache
    cache.invalidate()
    with SessionLocal() as db:
        cid = db.query(Category).filter(Category.name == "Cat2").one().id

    r = admin_client.post(
        f"/admin/categories/{cid}/edit",
        data={"name": "Cat1", "csrf_token": token},
        follow_redirects=True,
    )
    assert "уже существует" in r.text


# ============== Telegram 2FA ==============

def _enable_2fa(monkeypatch, sink: dict):
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
    r = client.get("/admin/login")
    token = extract_csrf(r.text)
    r = client.post(
        "/admin/login",
        data={"password": "test-password-123", "csrf_token": token},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/products"


def test_2fa_enabled_first_step_redirects_to_code(client, monkeypatch):
    sink: dict = {}
    _enable_2fa(monkeypatch, sink)

    r = client.get("/admin/login")
    token = extract_csrf(r.text)
    r = client.post(
        "/admin/login",
        data={"password": "test-password-123", "csrf_token": token},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login/2fa"
    assert "last_code" in sink
    assert len(sink["last_code"]) == 6
    assert sink["last_code"].isdigit()

    r = client.get("/admin/products", follow_redirects=False)
    assert r.status_code == 404


def test_2fa_full_flow(client, monkeypatch):
    sink: dict = {}
    _enable_2fa(monkeypatch, sink)

    r = client.get("/admin/login")
    token = extract_csrf(r.text)
    r = client.post(
        "/admin/login",
        data={"password": "test-password-123", "csrf_token": token},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login/2fa"

    r = client.get("/admin/login/2fa")
    assert r.status_code == 200
    assert "Код из Telegram" in r.text
    code_token = extract_csrf(r.text)

    r = client.post(
        "/admin/login/2fa",
        data={"code": "000000", "csrf_token": code_token},
    )
    assert r.status_code == 401
    assert "Неверный код" in r.text

    r = client.post(
        "/admin/login/2fa",
        data={"code": sink["last_code"], "csrf_token": code_token},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/products"

    r = client.get("/admin/products")
    assert r.status_code == 200


def test_2fa_wrong_code_too_many_attempts(client, monkeypatch):
    sink: dict = {}
    _enable_2fa(monkeypatch, sink)

    from app.routers.admin import auth as auth_mod
    monkeypatch.setattr(auth_mod, "TELEGRAM_CODE_MAX_ATTEMPTS", 3)

    r = client.get("/admin/login")
    token = extract_csrf(r.text)
    client.post(
        "/admin/login",
        data={"password": "test-password-123", "csrf_token": token},
        follow_redirects=False,
    )

    r = client.get("/admin/login/2fa")
    code_token = extract_csrf(r.text)

    for _ in range(3):
        r = client.post(
            "/admin/login/2fa",
            data={"code": "000000", "csrf_token": code_token},
        )
        assert r.status_code == 401

    r = client.post(
        "/admin/login/2fa",
        data={"code": "000000", "csrf_token": code_token},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login"


def test_2fa_purge_removes_expired_only():
    """_purge_expired удаляет только протухшие коды, живые не трогает."""
    import time
    from app.routers.admin import auth as auth_mod

    now = time.time()
    with auth_mod._codes_lock:
        auth_mod._pending_codes.clear()
        auth_mod._pending_codes["alive"] = {
            "code": "111111", "expires": now + 100, "attempts": 0,
        }
        auth_mod._pending_codes["dead"] = {
            "code": "222222", "expires": now - 100, "attempts": 0,
        }

    auth_mod._purge_expired()

    assert "alive" in auth_mod._pending_codes
    assert "dead" not in auth_mod._pending_codes