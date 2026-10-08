"""Идемпотентные миграции схемы при старте приложения.

Запускаются в lifespan: create_all -> run_startup_migrations -> seed.
"""
import sys

from sqlalchemy import inspect, text
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy.orm import Session

from app.core.database import engine
from app.data.models import Product, Brand, Category


def _migrate_brand_to_fk(db: Session) -> None:
    """products.brand (VARCHAR) -> products.brand_id (FK на brands.id)."""
    insp = inspect(engine)
    try:
        product_cols = {c["name"] for c in insp.get_columns("products")}
    except NoSuchTableError:
        return

    if "brand" not in product_cols:
        return

    if "brand_id" not in product_cols:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE products ADD COLUMN brand_id INTEGER "
                "REFERENCES brands(id)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_products_brand_id "
                "ON products (brand_id)"
            ))

    brand_cache: dict[str, Brand] = {
        b.name.lower(): b for b in db.query(Brand).all()
    }

    def get_or_create_brand(name: str) -> Brand:
        key = name.strip().lower()
        if key in brand_cache:
            return brand_cache[key]
        b = Brand(name=name.strip())
        db.add(b)
        db.flush()
        brand_cache[key] = b
        return b

    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, brand FROM products "
            "WHERE brand IS NOT NULL AND brand != ''"
        )).fetchall()

    migrated = 0
    for pid, brand_name in rows:
        product = db.query(Product).filter(Product.id == pid).first()
        if not product:
            continue
        product.brand_id = get_or_create_brand(brand_name).id
        migrated += 1

    if migrated:
        db.commit()
        print(f"✅ Бренды мигрированы у {migrated} товаров")

    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE products DROP COLUMN brand"))
    except Exception as e:
        print(
            f"⚠️  Не удалось удалить products.brand: {e}. "
            f"Колонка больше не используется, но осталась в схеме.",
            file=sys.stderr,
        )


def _migrate_name_lower(db: Session) -> None:
    """Добавляет products.name_lower и заполняет его."""
    insp = inspect(engine)
    try:
        product_cols = {c["name"] for c in insp.get_columns("products")}
    except NoSuchTableError:
        return

    if "name_lower" not in product_cols:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE products "
                "ADD COLUMN name_lower VARCHAR(200) NOT NULL DEFAULT ''"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_products_name_lower ON products (name_lower)"
            ))

    updated = 0
    for p in db.query(Product).all():
        expected = (p.name or "").strip().lower()
        if p.name_lower != expected:
            p.name_lower = expected
            updated += 1
    if updated:
        db.commit()


def _migrate_legacy_category_column(db: Session) -> None:
    """products.category (строка через запятую) -> M2M product_categories."""
    insp = inspect(engine)
    try:
        product_cols = {c["name"] for c in insp.get_columns("products")}
    except NoSuchTableError:
        return

    if "category" not in product_cols:
        return

    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, category FROM products "
            "WHERE category IS NOT NULL AND category != ''"
        )).fetchall()

    cat_cache: dict[str, Category] = {
        c.name.lower(): c for c in db.query(Category).all()
    }

    def get_or_create_cat(name: str) -> Category:
        key = name.strip().lower()
        if key in cat_cache:
            return cat_cache[key]
        c = Category(name=name.strip())
        db.add(c)
        db.flush()
        cat_cache[key] = c
        return c

    migrated = 0
    for product_id, cat_str in rows:
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            continue

        names = []
        for t in (cat_str or "").split(","):
            t = t.strip()
            if t and t not in names:
                names.append(t)

        product.categories = [get_or_create_cat(n) for n in names]
        migrated += 1

    if migrated:
        db.commit()
        print(f"✅ Категории мигрированы у {migrated} товаров")

    for col in ("category", "tags"):
        if col in product_cols:
            try:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE products DROP COLUMN {col}"))
            except Exception:
                with engine.begin() as conn:
                    conn.execute(text(f"UPDATE products SET {col} = NULL"))


def run_startup_migrations(db: Session) -> None:
    """Единая точка входа. Порядок важен: brand_id должен существовать
    до того, как мы трогаем name_lower и category."""
    _migrate_brand_to_fk(db)
    _migrate_name_lower(db)
    _migrate_legacy_category_column(db)