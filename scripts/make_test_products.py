"""Создать N тестовых товаров для проверки «Показать ещё».

Использование:
    python scripts/make_test_products.py          # 150 товаров
    python scripts/make_test_products.py 60       # 60 товаров
    python scripts/make_test_products.py --clean  # удалить все TEST-товары
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal
from app.data.models import Product, Brand, Category
from app.data import cache


PREFIX = "TEST-"


def make(count: int = 150) -> None:
    words = [
        "Крем", "Сыворотка", "Тоник", "Маска", "Пенка", "Лосьон",
        "Бальзам", "Скраб", "Масло", "Гель", "Эмульсия", "Мист",
        "Помада", "Тушь", "Тени", "Румяна", "Хайлайтер", "Консилер",
        "Парфюм", "Дезодорант", "Шампунь", "Кондиционер", "Гель для душа",
        "Соль для ванны", "Крем для рук", "Крем для ног", "Бальзам для губ",
        "Скраб для тела", "Мусс для укладки", "Спрей для волос",
    ]

    with SessionLocal() as db:
        brand = db.query(Brand).first()
        cats = db.query(Category).all()

        for i in range(count):
            name = f"{PREFIX}{random.choice(words)} #{i+1}"
            p = Product(
                name=name,
                price=random.randint(300, 5000),
                is_active=True,
                popular=random.random() < 0.2,
                brand_id=brand.id if brand else None,
            )
            if cats:
                p.categories = [random.choice(cats)]
            db.add(p)

        db.commit()

    cache.invalidate()
    print(f"✅ Создано {count} тестовых товаров с префиксом {PREFIX!r}")


def clean() -> None:
    with SessionLocal() as db:
        q = db.query(Product).filter(Product.name.like(f"{PREFIX}%"))
        n = q.count()
        for p in q.all():
            db.delete(p)
        db.commit()

    cache.invalidate()
    print(f"✅ Удалено {n} тестовых товаров с префиксом {PREFIX!r}")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "150"
    if arg == "--clean":
        clean()
    else:
        make(int(arg))