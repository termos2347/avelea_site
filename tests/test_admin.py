from tests.conftest import extract_csrf


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


def test_upload_rejects_non_image(admin_client):
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

    r = admin_client.get("/admin/products?q=Мусорный")
    assert "Мусорный файл" in r.text
    # Файл не должен был сохраниться — картинка отсутствует
    assert "/static/uploads/" not in r.text