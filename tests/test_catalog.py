"""Тесты публичного каталога: скрытые товары, пагинация, infinite scroll."""
from tests.conftest import extract_csrf  # noqa: F401


def _add_product_via_db(name: str, is_active: bool = True, price: int = 100) -> tuple[int, str]:
    """Создаёт товар напрямую в БД. Возвращает (id, slug)."""
    from app.core.database import SessionLocal
    from app.data.models import Product, Brand
    from app.data import cache

    with SessionLocal() as db:
        brand = db.query(Brand).first()
        p = Product(
            name=name,
            price=price,
            is_active=is_active,
            brand_id=brand.id if brand else None,
        )
        db.add(p)
        db.commit()
        pid = p.id
        slug = p.slug

    cache.invalidate()
    return pid, slug


# ============== Скрытые товары ==============

def test_hidden_product_not_in_catalog(client):
    """is_active=False → не в /catalog, не в sitemap, 404 на странице."""
    pid, slug = _add_product_via_db("Скрытый-товар-XYZ", is_active=False)

    r = client.get("/catalog")
    assert "Скрытый-товар-XYZ" not in r.text

    r = client.get("/sitemap.xml")
    assert f"/product/{slug}" not in r.text

    r = client.get(f"/product/{slug}")
    assert r.status_code == 404


def test_hidden_product_by_id_404(client):
    """Через ID тоже 404, если товар скрыт."""
    pid, _ = _add_product_via_db("Скрытый-ID-XYZ", is_active=False)

    r = client.get(f"/product/{pid}", follow_redirects=False)
    assert r.status_code == 404


def test_active_product_visible(client):
    """Активный товар — виден везде: каталог, sitemap, страница."""
    pid, slug = _add_product_via_db("Видимый-товар-XYZ", is_active=True)

    r = client.get("/catalog")
    assert "Видимый-товар-XYZ" in r.text

    r = client.get("/sitemap.xml")
    assert f"/product/{slug}" in r.text

    r = client.get(f"/product/{slug}")
    assert r.status_code == 200


def test_hidden_product_in_admin_list(admin_client):
    """Скрытый товар всё равно виден в админке (is_active=False)."""
    _add_product_via_db("Скрыт-но-в-админке-XYZ", is_active=False)

    r = admin_client.get("/admin/products", params={"q": "Скрыт-но-в-админке"})
    assert "Скрыт-но-в-админке-XYZ" in r.text


# ============== Пагинация ==============

def test_catalog_pagination_first_page(client):
    """21 товар при 12 на страницу → есть ссылка на 2-ю."""
    from app.core.database import SessionLocal
    from app.data.models import Product, Brand
    from app.data import cache

    with SessionLocal() as db:
        brand = db.query(Brand).first()
        for i in range(20):
            db.add(Product(
                name=f"Pagin-{i:02d}",
                price=100 + i,
                is_active=True,
                brand_id=brand.id if brand else None,
            ))
        db.commit()

    cache.invalidate()

    r = client.get("/catalog")
    assert r.status_code == 200
    assert "page=2" in r.text


def test_catalog_pagination_second_page(client):
    """Вторая страница открывается без ошибки."""
    from app.core.database import SessionLocal
    from app.data.models import Product, Brand
    from app.data import cache

    with SessionLocal() as db:
        brand = db.query(Brand).first()
        for i in range(20):
            db.add(Product(
                name=f"Pagin2-{i:02d}",
                price=100 + i,
                is_active=True,
                brand_id=brand.id if brand else None,
            ))
        db.commit()

    cache.invalidate()

    r = client.get("/catalog?page=2")
    assert r.status_code == 200


def test_catalog_pagination_out_of_bounds(client):
    """page=999 при малом числе товаров → последняя страница, не 500."""
    r = client.get("/catalog?page=999")
    assert r.status_code == 200


# ============== Поиск и фильтры на скрытых ==============

def test_hidden_product_not_in_search(client):
    """Скрытый товар не появляется в поиске."""
    _add_product_via_db("Скрыт-поиск-XYZ", is_active=False)

    r = client.get("/catalog?q=Скрыт-поиск")
    assert "ничего не найдено" in r.text.lower() or "Скрыт-поиск-XYZ" not in r.text


# ============== Infinite scroll (/catalog/more) ==============

def test_catalog_more_returns_only_items(client):
    """/catalog/more отдаёт фрагмент: карточки + meta, без <html>."""
    from app.core.database import SessionLocal
    from app.data.models import Product, Brand
    from app.data import cache

    with SessionLocal() as db:
        brand = db.query(Brand).first()
        for i in range(20):
            db.add(Product(
                name=f"More-{i:02d}",
                price=100 + i,
                is_active=True,
                brand_id=brand.id if brand else None,
            ))
        db.commit()

    cache.invalidate()

    r = client.get("/catalog/more?page=1")
    assert r.status_code == 200

    # Не полная страница
    assert "<!DOCTYPE html>" not in r.text
    assert "<html" not in r.text

    # Есть items и meta
    assert "More-00" in r.text
    assert "data-catalog-meta" in r.text
    assert 'data-has-next="1"' in r.text


def test_catalog_more_last_page_has_no_next(client):
    """На последней странице data-has-next="0"."""
    from app.core.database import SessionLocal
    from app.data.models import Product, Brand
    from app.data import cache

    with SessionLocal() as db:
        brand = db.query(Brand).first()
        for i in range(20):
            db.add(Product(
                name=f"Last-{i:02d}",
                price=100 + i,
                is_active=True,
                brand_id=brand.id if brand else None,
            ))
        db.commit()

    cache.invalidate()

    # 20 товаров + 1 демо = 21. PER_PAGE=12 → 2 страницы.
    # page=2 — последняя.
    r = client.get("/catalog/more?page=2")
    assert r.status_code == 200
    assert 'data-has-next="0"' in r.text