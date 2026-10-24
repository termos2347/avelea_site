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

# Кэш sitemap.xml по base_url. Сбрасывается в invalidate() вместе с
# остальным кэшем. Ключ — base_url, чтобы http://localhost:8000
# и https://avelea.ru не смешивались.
_sitemap_cache: dict[str, str] = {}


def reload_all() -> None:
    """Полностью перечитывает кэш из БД.

    ВАЖНО: DB-запросы выполняются ВНЕ _lock. Под локом — только
    присваивание готовых данных. Иначе на холодном кэше
    (после рестарта или invalidate) все читатели ждут, пока
    SQLAlchemy сходит в БД.
    """
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
        _sitemap_cache.clear()


def invalidate() -> None:
    """Сбрасывает кэш. Следующий публичный запрос перечитает из БД."""
    with _lock:
        _state["products"] = None
        _state["categories"] = None
        _state["brands"] = None
        _state["settings"] = None
        _sitemap_cache.clear()


def _ensure_loaded() -> None:
    """Double-checked locking: проверяем под локом, грузим — снаружи.

    Два потока, одновременно промахнувшихся мимо кэша, оба вызовут
    reload_all() — это idempotent, просто немного лишней работы.
    Никаких блокировок читателей на время DB-запроса.
    """
    with _lock:
        if _state["products"] is not None:
            return
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


def get_sitemap(base_url: str) -> str | None:
    """Закэшированный sitemap.xml для данного base_url, если есть."""
    _ensure_loaded()
    with _lock:
        return _sitemap_cache.get(base_url)


def set_sitemap(base_url: str, xml: str) -> None:
    with _lock:
        _sitemap_cache[base_url] = xml