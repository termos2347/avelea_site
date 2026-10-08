"""Чистые функции: URL-билдеры, парсинг формы товара, resolve-хелперы.

Никаких зависимостей от FastAPI — только SQLAlchemy-сессия и модели.
"""
import re
from urllib.parse import urlencode

from sqlalchemy.orm import Session

from app.data.models import Brand, Category


# ============================================================
# URL-билдеры для каталога и пагинации
# ============================================================

def build_filter_url(params, remove_key: str, remove_value: str | None = None) -> str:
    """Возвращает /catalog?... без одного фильтра (для чипов)."""
    pairs = []
    for k in params.keys():
        for v in params.getlist(k):
            if k == remove_key and (remove_value is None or v == remove_value):
                continue
            pairs.append((k, v))
    qs = urlencode(pairs)
    return "/catalog" + ("?" + qs if qs else "")


def build_page_url(params, page_num: int, base_path: str = "/catalog") -> str:
    """URL той же страницы с подменённым ?page=N."""
    pairs = []
    for k in params.keys():
        if k == "page":
            continue
        for v in params.getlist(k):
            pairs.append((k, v))
    pairs.append(("page", str(page_num)))
    return base_path + "?" + urlencode(pairs)


def build_reset_url() -> str:
    return "/catalog"


def make_page_items(current: int, total: int, params, base_path: str = "/catalog"):
    """Готовит список элементов пагинации для шаблона.

    Возвращает список словарей: {'num': int, 'url': str, 'current': bool}
    либо {'ellipsis': True} для пропуска.
    """
    if total <= 1:
        return []

    if total <= 7:
        raw = list(range(1, total + 1))
    else:
        raw_set = sorted({1, total, current - 1, current, current + 1})
        raw = []
        prev = 0
        for p in raw_set:
            if 1 <= p <= total:
                if p - prev > 1:
                    raw.append(None)
                raw.append(p)
                prev = p

    items = []
    for p in raw:
        if p is None:
            items.append({"ellipsis": True})
        else:
            items.append({
                "num": p,
                "url": build_page_url(params, p, base_path),
                "current": (p == current),
            })
    return items


# ============================================================
# Парсинг / валидация полей формы товара
# ============================================================

def parse_volume(volume: str | None) -> tuple[str, str]:
    """'150 мл' -> ('150', 'мл'); '4.5 г' -> ('4.5', 'г').

    Если строка не распознана — возвращает ('', 'мл').
    """
    if not volume:
        return "", "мл"

    m = re.match(r"^\s*([\d.,]+)\s*([а-яa-z]*)\s*$", volume, re.IGNORECASE)
    if not m:
        return "", "мл"

    amount = m.group(1).replace(",", ".")
    unit = (m.group(2) or "").strip().lower()

    if unit in ("г", "гр", "g", "gr", "gram"):
        unit = "г"
    else:
        unit = "мл"

    return amount, unit


def validate_price(price: int) -> str | None:
    """Возвращает текст ошибки, если цена невалидна, иначе None."""
    if price < 0:
        return "Цена не может быть отрицательной — изменения не сохранены."
    return None


# ============================================================
# resolve-хелперы (работают с БД через переданную сессию)
# ============================================================

def resolve_categories(db: Session, names: list[str]) -> list[Category]:
    """По списку имён возвращает ORM-объекты категорий."""
    if not names:
        return []
    return db.query(Category).filter(Category.name.in_(names)).all()


def resolve_brand_id(db: Session, raw: str) -> int | None:
    """Проверяет, что бренд с таким id существует, и возвращает его id."""
    raw = (raw or "").strip()
    if not raw or not raw.isdigit():
        return None
    bid = int(raw)
    exists = db.query(Brand).filter(Brand.id == bid).first()
    return bid if exists else None