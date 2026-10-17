"""Идемпотентные миграции схемы при старте приложения.

Запускаются в lifespan: create_all -> run_startup_migrations -> seed.
"""
import logging

from sqlalchemy import inspect, text
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy.orm import Session

from app.core.database import engine
from app.data.models import Product, Brand, Category

log = logging.getLogger(__name__)


def _migrate_add_slug_column(db: Session) -> None:
    """Добавляет products.slug для человекочитаемых URL."""
    insp = inspect(engine)
    try:
        product_cols = {c["name"] for c in insp.get_columns("products")}
    except NoSuchTableError:
        return

    if "slug" in product_cols:
        return

    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE products ADD COLUMN slug VARCHAR(250)"
        ))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_products_slug "
            "ON products (slug)"
        ))
    log.info("Добавлена колонка products.slug")


def _migrate_add_gallery_and_sections(db: Session) -> None:
    """Добавляет колонки галереи и секций."""
    insp = inspect(engine)
    try:
        product_cols = {c["name"] for c in insp.get_columns("products")}
    except NoSuchTableError:
        return

    to_add: list[str] = []
    if "image_2" not in product_cols:
        to_add.append("ALTER TABLE products ADD COLUMN image_2 VARCHAR(200)")
    if "image_3" not in product_cols:
        to_add.append("ALTER TABLE products ADD COLUMN image_3 VARCHAR(200)")
    if "image_4" not in product_cols:
        to_add.append("ALTER TABLE products ADD COLUMN image_4 VARCHAR(200)")
    if "composition" not in product_cols:
        to_add.append("ALTER TABLE products ADD COLUMN composition TEXT")
    if "usage" not in product_cols:
        to_add.append("ALTER TABLE products ADD COLUMN usage TEXT")

    if not to_add:
        return

    with engine.begin() as conn:
        for sql in to_add:
            conn.execute(text(sql))

    log.info("Добавлены колонки галереи/секций: %d", len(to_add))


def _migrate_add_brand_description(db: Session) -> None:
    """Добавляет brands.description (описание бренда)."""
    insp = inspect(engine)
    try:
        brand_cols = {c["name"] for c in insp.get_columns("brands")}
    except NoSuchTableError:
        return

    if "description" in brand_cols:
        return

    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE brands ADD COLUMN description TEXT"
        ))
    log.info("Добавлено поле brands.description")


def _migrate_add_is_active(db: Session) -> None:
    """Добавляет products.is_active для скрытия товара без удаления."""
    insp = inspect(engine)
    try:
        product_cols = {c["name"] for c in insp.get_columns("products")}
    except NoSuchTableError:
        return

    if "is_active" in product_cols:
        return

    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE products "
            "ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT true"
        ))
    log.info("Добавлена колонка products.is_active")


def _migrate_drop_layout_column(db: Session) -> None:
    """Удаляет устаревшую колонку products.image_layout."""
    insp = inspect(engine)
    try:
        product_cols = {c["name"] for c in insp.get_columns("products")}
    except NoSuchTableError:
        return

    if "image_layout" not in product_cols:
        return

    try:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE products DROP COLUMN image_layout"
            ))
        log.info("Удалена устаревшая колонка products.image_layout")
    except Exception as e:
        log.warning("Не удалось удалить products.image_layout: %s", e)


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
        log.info("Бренды мигрированы у %d товаров", migrated)

    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE products DROP COLUMN brand"))
    except Exception as e:
        log.warning(
            "Не удалось удалить products.brand: %s. "
            "Колонка больше не используется, но осталась в схеме.",
            e,
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
        log.info("Категории мигрированы у %d товаров", migrated)

    for col in ("category", "tags"):
        if col in product_cols:
            try:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE products DROP COLUMN {col}"))
            except Exception:
                with engine.begin() as conn:
                    conn.execute(text(f"UPDATE products SET {col} = NULL"))


def run_startup_migrations(db: Session) -> None:
    """Единая точка входа.

    Порядок критичен:
      1. ALTER-миграции ПЕРВЫМИ — до любых ORM-запросов.
      2. Остальные миграции через ORM.
    """
    _migrate_add_slug_column(db)
    _migrate_add_gallery_and_sections(db)
    _migrate_add_brand_description(db)
    _migrate_add_is_active(db)
    _migrate_drop_layout_column(db)

    _migrate_brand_to_fk(db)
    _migrate_name_lower(db)
    _migrate_legacy_category_column(db)