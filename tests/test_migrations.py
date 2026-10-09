"""Тесты миграций схемы.

Каждый тест создаёт свежую SQLite-БД со «старой» схемой,
подменяет module-level engine в app.data.migrations на неё,
прогоняет миграции и проверяет результат.

Это важно, потому что миграции пишут в схему БД и работают
на живых данных при первом запуске новой версии приложения.
"""
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.data import migrations as mig


# ============================================================
# Хелперы
# ============================================================

def _make_engine(tmp_path):
    return create_engine(f"sqlite:///{tmp_path / 'mig.db'}")


def _create_base_tables(engine):
    """brands, categories, product_categories — общие для всех тестов."""
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE brands ("
            "id INTEGER PRIMARY KEY, name VARCHAR(100) UNIQUE NOT NULL)"
        ))
        conn.execute(text(
            "CREATE TABLE categories ("
            "id INTEGER PRIMARY KEY, name VARCHAR(100) UNIQUE NOT NULL)"
        ))
        conn.execute(text(
            "CREATE TABLE product_categories ("
            "product_id INTEGER, category_id INTEGER, "
            "PRIMARY KEY (product_id, category_id))"
        ))


def _create_products_table(engine, *, with_brand=False,
                           with_category=False, with_tags=False,
                           with_name_lower=True):
    """Создаёт products с колонками текущего ORM-модели
    плюс опциональными legacy-колонками.

    Все колонки, которые ждёт ORM (id, name, name_lower, brand_id,
    price, popular, description, volume, image), должны присутствовать,
    иначе db.query(Product) внутри миграций упадёт.
    """
    cols = [
        "id INTEGER PRIMARY KEY",
        "name VARCHAR(200) NOT NULL",
        "brand_id INTEGER",
        "price INTEGER NOT NULL DEFAULT 0",
        "popular BOOLEAN DEFAULT 0",
        "description TEXT",
        "volume VARCHAR(50)",
        "image VARCHAR(200)",
    ]
    if with_name_lower:
        cols.insert(2, "name_lower VARCHAR(200) NOT NULL DEFAULT ''")
    if with_brand:
        cols.append("brand VARCHAR(100)")
    if with_category:
        cols.append("category VARCHAR(200)")
    if with_tags:
        cols.append("tags VARCHAR(200)")

    with engine.begin() as conn:
        conn.execute(text(f"CREATE TABLE products ({', '.join(cols)})"))


def _setup(engine, *, with_brand=False, with_category=False,
           with_tags=False, with_name_lower=True):
    _create_base_tables(engine)
    _create_products_table(
        engine,
        with_brand=with_brand,
        with_category=with_category,
        with_tags=with_tags,
        with_name_lower=with_name_lower,
    )


# ============================================================
# _migrate_brand_to_fk
# ============================================================

def test_brand_migration_copies_data(tmp_path, monkeypatch):
    engine = _make_engine(tmp_path)
    monkeypatch.setattr(mig, "engine", engine)
    _setup(engine, with_brand=True)

    with engine.begin() as conn:
        conn.execute(text("INSERT INTO brands (id, name) VALUES (1, 'Avelea')"))
        conn.execute(text(
            "INSERT INTO products (name, name_lower, brand, price) "
            "VALUES ('Крем', 'крем', 'Avelea', 1000)"
        ))
        conn.execute(text(
            "INSERT INTO products (name, name_lower, brand, price) "
            "VALUES ('Без бренда', 'без бренда', NULL, 300)"
        ))

    with sessionmaker(bind=engine)() as db:
        mig._migrate_brand_to_fk(db)

    cols = {c["name"] for c in inspect(engine).get_columns("products")}
    assert "brand_id" in cols
    assert "brand" not in cols

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, brand_id FROM products ORDER BY id")
        ).fetchall()

    assert rows[0][1] == 1        # Крем привязан к Avelea
    assert rows[1][1] is None     # Без бренда — NULL


def test_brand_migration_creates_new_brand(tmp_path, monkeypatch):
    """Если в products.brand стоит имя, которого нет в brands — оно создаётся."""
    engine = _make_engine(tmp_path)
    monkeypatch.setattr(mig, "engine", engine)
    _setup(engine, with_brand=True)

    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO products (name, name_lower, brand, price) "
            "VALUES ('Х', 'х', 'NewBrand', 100)"
        ))

    with sessionmaker(bind=engine)() as db:
        mig._migrate_brand_to_fk(db)

    with engine.connect() as conn:
        names = {r[0] for r in conn.execute(
            text("SELECT name FROM brands")
        ).fetchall()}
        assert "NewBrand" in names

        brand_id = conn.execute(
            text("SELECT brand_id FROM products WHERE id=1")
        ).scalar()
        assert brand_id is not None


def test_brand_migration_idempotent(tmp_path, monkeypatch):
    """Повторный прогон на уже мигрированной схеме ничего не ломает."""
    engine = _make_engine(tmp_path)
    monkeypatch.setattr(mig, "engine", engine)
    _setup(engine, with_brand=True)

    with engine.begin() as conn:
        conn.execute(text("INSERT INTO brands (id, name) VALUES (1, 'Avelea')"))
        conn.execute(text(
            "INSERT INTO products (name, name_lower, brand, price) "
            "VALUES ('Крем', 'крем', 'Avelea', 1000)"
        ))

    with sessionmaker(bind=engine)() as db:
        mig._migrate_brand_to_fk(db)
    with sessionmaker(bind=engine)() as db:
        mig._migrate_brand_to_fk(db)

    with engine.connect() as conn:
        assert conn.execute(
            text("SELECT brand_id FROM products WHERE id=1")
        ).scalar() == 1


def test_brand_migration_noop_on_new_schema(tmp_path, monkeypatch):
    """Если колонки brand нет — миграция тихо выходит, ничего не портя."""
    engine = _make_engine(tmp_path)
    monkeypatch.setattr(mig, "engine", engine)
    _setup(engine, with_brand=False)

    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO products (name, name_lower, brand_id, price) "
            "VALUES ('Крем', 'крем', 42, 1000)"
        ))

    with sessionmaker(bind=engine)() as db:
        mig._migrate_brand_to_fk(db)

    with engine.connect() as conn:
        # Данные не тронуты
        assert conn.execute(
            text("SELECT brand_id FROM products WHERE id=1")
        ).scalar() == 42


# ============================================================
# _migrate_name_lower
# ============================================================

def test_name_lower_adds_column_and_fills(tmp_path, monkeypatch):
    engine = _make_engine(tmp_path)
    monkeypatch.setattr(mig, "engine", engine)
    _setup(engine, with_name_lower=False)

    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO products (name, price) VALUES ('Крем', 100)"
        ))
        conn.execute(text(
            "INSERT INTO products (name, price) VALUES ('  Тушь  ', 200)"
        ))

    with sessionmaker(bind=engine)() as db:
        mig._migrate_name_lower(db)

    cols = {c["name"] for c in inspect(engine).get_columns("products")}
    assert "name_lower" in cols

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT name_lower FROM products ORDER BY id")
        ).fetchall()
    assert rows[0][0] == "крем"
    assert rows[1][0] == "тушь"   # пробелы срезаны


def test_name_lower_fixes_wrong_values(tmp_path, monkeypatch):
    """Если name_lower уже есть, но данные кривые — они пересчитываются."""
    engine = _make_engine(tmp_path)
    monkeypatch.setattr(mig, "engine", engine)
    _setup(engine, with_name_lower=True)

    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO products (name, name_lower, price) "
            "VALUES ('Крем', 'КРЕМ', 100)"
        ))

    with sessionmaker(bind=engine)() as db:
        mig._migrate_name_lower(db)

    with engine.connect() as conn:
        assert conn.execute(
            text("SELECT name_lower FROM products WHERE id=1")
        ).scalar() == "крем"


# ============================================================
# _migrate_legacy_category_column
# ============================================================

def test_category_migration_moves_to_m2m(tmp_path, monkeypatch):
    engine = _make_engine(tmp_path)
    monkeypatch.setattr(mig, "engine", engine)
    _setup(engine, with_category=True, with_tags=True)

    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO products (name, name_lower, category, price) "
            "VALUES ('Крем', 'крем', 'Лицо', 100)"
        ))
        conn.execute(text(
            "INSERT INTO products (name, name_lower, category, price) "
            "VALUES ('Тушь', 'тушь', 'Макияж,Лицо', 200)"
        ))

    with sessionmaker(bind=engine)() as db:
        mig._migrate_legacy_category_column(db)

    with engine.connect() as conn:
        names = {r[0] for r in conn.execute(
            text("SELECT name FROM categories")
        ).fetchall()}
        assert names == {"Лицо", "Макияж"}

        links = conn.execute(text(
            "SELECT pc.product_id, c.name "
            "FROM product_categories pc "
            "JOIN categories c ON c.id = pc.category_id"
        )).fetchall()
        links = {(r[0], r[1]) for r in links}

        assert (1, "Лицо") in links
        assert (2, "Лицо") in links
        assert (2, "Макияж") in links


def test_category_migration_noop_without_column(tmp_path, monkeypatch):
    """Если колонки category нет — миграция выходит, не трогая данные."""
    engine = _make_engine(tmp_path)
    monkeypatch.setattr(mig, "engine", engine)
    _setup(engine, with_category=False)

    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO products (name, name_lower, price) "
            "VALUES ('Крем', 'крем', 100)"
        ))

    with sessionmaker(bind=engine)() as db:
        mig._migrate_legacy_category_column(db)

    with engine.connect() as conn:
        assert conn.execute(
            text("SELECT COUNT(*) FROM products")
        ).scalar() == 1
        assert conn.execute(
            text("SELECT COUNT(*) FROM categories")
        ).scalar() == 0


# ============================================================
# run_startup_migrations — полный прогон
# ============================================================

def test_run_all_migrations_on_old_schema(tmp_path, monkeypatch):
    """Полный сценарий: старая схема со всеми legacy-колонками.

    Проверяет, что run_startup_migrations отрабатывает целиком
    и приводит схему к актуальному виду.
    """
    engine = _make_engine(tmp_path)
    monkeypatch.setattr(mig, "engine", engine)
    _setup(
        engine,
        with_brand=True,
        with_category=True,
        with_tags=True,
        with_name_lower=True,
    )

    with engine.begin() as conn:
        conn.execute(text("INSERT INTO brands (id, name) VALUES (1, 'Avelea')"))
        conn.execute(text(
            "INSERT INTO products "
            "(name, name_lower, brand, category, price) "
            "VALUES ('Крем', 'крем', 'Avelea', 'Лицо', 100)"
        ))

    with sessionmaker(bind=engine)() as db:
        mig.run_startup_migrations(db)

    cols = {c["name"] for c in inspect(engine).get_columns("products")}
    assert "brand_id" in cols
    assert "brand" not in cols
    assert "category" not in cols
    assert "tags" not in cols

    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT brand_id FROM products WHERE id=1"
        )).fetchone()
        assert row[0] == 1

        links = conn.execute(text(
            "SELECT COUNT(*) FROM product_categories WHERE product_id=1"
        )).scalar()
        assert links == 1