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
    assert "Ничего не найдено" in r.text


def test_product_page(client):
    r = client.get("/product/1")
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