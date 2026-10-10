def test_index(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "avelea" in r.text.lower()


def test_catalog(client):
    r = client.get("/catalog")
    assert r.status_code == 200
    assert "Каталог" in r.text


def test_catalog_search(client):
    r = client.get("/catalog?q=крем")
    assert r.status_code == 200
    assert "крем" in r.text.lower()


def test_catalog_search_cyrillic_case_insensitive(client):
    """Поиск должен работать вне зависимости от регистра для кириллицы.

    Раньше поиск шёл через ilike, а SQLite LOWER() кириллицу не умеет,
    поэтому «КРЕМ» не находил «Увлажняющий крем».
    """
    r = client.get("/catalog?q=КРЕМ")
    assert r.status_code == 200
    assert "Увлажняющий крем" in r.text

    r = client.get("/catalog?q=крем")
    assert r.status_code == 200
    assert "Увлажняющий крем" in r.text


def test_catalog_search_no_results(client):
    r = client.get("/catalog?q=абвгд-нет-такого")
    assert r.status_code == 200
    assert "ничего не найдено" in r.text.lower()


def test_product_page(client):
    from app.core.database import SessionLocal
    from app.data.models import Product

    with SessionLocal() as db:
        pid = db.query(Product).first().id

    r = client.get(f"/product/{pid}")
    assert r.status_code == 200


def test_product_not_found(client):
    r = client.get("/product/999999")
    assert r.status_code == 404


def test_site_404(client):
    r = client.get("/nope")
    assert r.status_code == 404


def test_about(client):
    r = client.get("/about")
    assert r.status_code == 200


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_security_headers(client):
    r = client.get("/")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert r.headers["cross-origin-opener-policy"] == "same-origin"


# ============== Контекстные 404 ==============

def test_404_context_product(client):
    """404 на /product/* показывает специфичный текст, не общий."""
    r = client.get("/product/999999")
    assert r.status_code == 404
    assert "Товар не найден" in r.text


def test_404_context_generic(client):
    """Произвольный URL — общий текст «Страница не найдена»."""
    r = client.get("/nope")
    assert r.status_code == 404
    assert "Страница не найдена" in r.text


def test_admin_404_does_not_leak_admin(client):
    """Неавторизованный /admin/* не палит существование админки.

    Раньше отдавался редирект на /admin/login — это подтверждало
    существование админки. Теперь AdminGuardMiddleware отдаёт
    обычную 404 без единого намёка.
    """
    r = client.get("/admin/whatever-this-is", follow_redirects=False)
    assert r.status_code == 404

    body = r.text.lower()
    assert "admin" not in body
    assert "админ" not in body
    assert "csrf" not in body
    assert "логин" not in body
    assert "login" not in body


def test_admin_login_is_reachable(client):
    """Но /admin/login при этом доступен — иначе как войти."""
    r = client.get("/admin/login")
    assert r.status_code == 200
    assert "Вход в админку" in r.text


# ============== SEO ==============

def test_sitemap_xml(client):
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/xml")
    assert "<urlset" in r.text
    assert "/catalog" in r.text
    assert "/about" in r.text
    # В сиде есть товары — значит, в sitemap должны быть /product/*
    assert "/product/" in r.text
    
def test_admin_login_has_noindex_header(client):
    """Все ответы /admin/* несут X-Robots-Tag — роботы не индексируют."""
    r = client.get("/admin/login")
    assert r.status_code == 200
    assert r.headers.get("x-robots-tag") == "noindex, nofollow"

    # И 404 для неавторизованных — тоже с заголовком
    r = client.get("/admin/whatever", follow_redirects=False)
    assert r.status_code == 404
    assert r.headers.get("x-robots-tag") == "noindex, nofollow"


def test_robots_txt_does_not_mention_admin(client):
    """robots.txt не подсказывает злодеям про /admin."""
    r = client.get("/robots.txt")
    assert r.status_code == 200
    assert "/admin" not in r.text