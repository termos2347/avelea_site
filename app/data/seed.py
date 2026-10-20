"""Наполнение БД стартовыми данными (идемпотентно)."""
import logging
import os

from sqlalchemy.orm import Session

from app.data.models import Product, Brand, Category, Setting

log = logging.getLogger(__name__)


SEED_MARKER_KEY = "seeded_v1"
BASE_CATEGORIES = ("Лицо", "Макияж", "Тело", "Парфюм")


def _demo_product_enabled() -> bool:
    v = os.getenv("SEED_DEMO_PRODUCT", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def seed_database(db: Session) -> None:
    marker = db.query(Setting).filter(Setting.key == SEED_MARKER_KEY).first()
    if marker and marker.value == "1":
        return

    if db.query(Product).count() > 0:
        db.add(Setting(key=SEED_MARKER_KEY, value="1"))
        db.commit()
        return

    cat_cache: dict[str, Category] = {c.name.lower(): c for c in db.query(Category).all()}

    def cat(name: str) -> Category:
        key = name.strip().lower()
        if key in cat_cache:
            return cat_cache[key]
        c = Category(name=name.strip())
        db.add(c)
        db.flush()
        cat_cache[key] = c
        return c

    brand_cache = {b.name.lower(): b for b in db.query(Brand).all()}
    if "avelea" not in brand_cache:
        b = Brand(name="Avelea")
        db.add(b)
        db.flush()
        brand_cache["avelea"] = b
    avelea_brand = brand_cache["avelea"]

    for cat_name in BASE_CATEGORIES:
        cat(cat_name)

    if _demo_product_enabled():
        db.add(Product(
            name="Древесный парфюм Bois",
            categories=[cat("Парфюм")],
            brand_id=avelea_brand.id,
            price=3900,
            popular=False,
            description="Тёплый древесный аромат с сандалом, ванилью и амброй.",
            volume="50 мл",
        ))

    db.add(Setting(key=SEED_MARKER_KEY, value="1"))
    db.commit()
    log.info("База данных инициализирована (demo=%s)", _demo_product_enabled())