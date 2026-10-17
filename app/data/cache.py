"""In-memory кэш товаров, категорий, брендов и настроек.

Как работает:
  - при первом обращении (или при старте) читает всё из БД один раз;
  - публичные страницы (/, /catalog, /product/{id}, /about) работают
    с кэшем, а не ходят в БД на каждый запрос;
  - после любой write-операции в админке вызывается invalidate() —
    кэш сбрасывается, при следующем запросе перечитается заново.

Потокобезопасно: RLock + double-checked locking.
"""
from threading import RLock

from app.core.database import SessionLocal
from app.data.models import Product, Brand, Category, Setting


_lock = RLock()
_state = {
    "products": None,     # list[Product] с eager categories + brand_ref
    "categories": None,   # list[Category]
    "brands": None,       # list[Brand]
    "settings": None,     # dict[str, str] — все ключи Setting
}


def reload_all() -> None:
    """Полностью перечитывает кэш из БД."""
    db = SessionLocal()
    try:
        products = db.query(Product).order_by(Product.id.asc()).all()
        categories = db.query(Category).order_by(Category.name).all()
        brands = db.query(Brand).order_by(Brand.name).all()
        settings = {s.key: s.value for s in db.query(Setting).all()}
    finally:
        db.close()

    with _lock:
        _state["products"] = products
        _state["categories"] = categories
        _state["brands"] = brands
        _state["settings"] = settings


def invalidate() -> None:
    """Сбрасывает кэш. Следующий публичный запрос перечитает из БД."""
    with _lock:
        _state["products"] = None
        _state["categories"] = None
        _state["brands"] = None
        _state["settings"] = None


def _ensure_loaded() -> None:
    with _lock:
        if _state["products"] is None:
            reload_all()


def get_products() -> list[Product]:
    _ensure_loaded()
    return list(_state["products"])


def get_categories() -> list[Category]:
    _ensure_loaded()
    return list(_state["categories"])


def get_brands() -> list[Brand]:
    _ensure_loaded()
    return list(_state["brands"])


def get_brand_names() -> list[str]:
    _ensure_loaded()
    return [b.name for b in _state["brands"]]


def get_settings() -> dict[str, str]:
    """Копия dict'а настроек. None-значения заменены на пустые строки."""
    _ensure_loaded()
    return {k: (v or "") for k, v in _state["settings"].items()}