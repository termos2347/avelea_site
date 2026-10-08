"""In-memory кэш товаров, категорий и брендов.

Как работает:
  - при первом обращении (или при старте) читает всё из БД один раз;
  - публичные страницы (/, /catalog, /product/{id}) работают с кэшем,
    а не ходят в БД на каждый запрос;
  - после любой write-операции в админке вызывается invalidate() —
    кэш сбрасывается, при следующем запросе перечитается заново.

Никаких сетевых задержек до Neon на публичных страницах.
Никакой рассинхронизации: админ поменял → сброс → сайт видит новое.

Потокобезопасно: RLock + double-checked locking.
"""
from threading import RLock

from app.core.database import SessionLocal
from app.data.models import Product, Brand, Category


_lock = RLock()
_state = {
    "products": None,     # list[Product] с eager categories + brand_ref
    "categories": None,   # list[Category]
    "brands": None,       # list[str] — только имена
}


def reload_all() -> None:
    """Полностью перечитывает кэш из БД.

    Все объекты загружаются в одной сессии, которая тут же закрывается —
    но благодаря lazy="selectin" (categories) и lazy="joined" (brand_ref)
    все нужные связи уже подтянуты, и detached-объекты продолжают
    работать как обычно.
    """
    db = SessionLocal()
    try:
        products = db.query(Product).order_by(Product.id.asc()).all()
        categories = db.query(Category).order_by(Category.name).all()
        brands = db.query(Brand).order_by(Brand.name).all()
    finally:
        db.close()

    with _lock:
        _state["products"] = products
        _state["categories"] = categories
        _state["brands"] = brands


def invalidate() -> None:
    """Сбрасывает кэш. Следующий публичный запрос перечитает из БД."""
    with _lock:
        _state["products"] = None
        _state["categories"] = None
        _state["brands"] = None


def _ensure_loaded() -> None:
    """Ленивая загрузка: если кэш пуст — читаем из БД."""
    with _lock:
        if _state["products"] is None:
            reload_all()


def get_products() -> list[Product]:
    _ensure_loaded()
    return _state["products"]


def get_categories() -> list[Category]:
    _ensure_loaded()
    return _state["categories"]


def get_brands() -> list[Brand]:
    """Возвращает ORM-объекты Brand, отсортированные по имени."""
    _ensure_loaded()
    return _state["brands"]


def get_brand_names() -> list[str]:
    """Возвращает только имена брендов (для фильтров каталога)."""
    _ensure_loaded()
    return [b.name for b in _state["brands"]]