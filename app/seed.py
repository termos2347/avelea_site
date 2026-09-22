"""Наполнение БД тестовыми данными.

Используется только при первом запуске (когда таблица products пуста).
Функция seed_database() идемпотентна: повторный вызов ничего не сделает.

ВАЖНО про SQLite и кириллицу:
    SQLite-функция LOWER() умеет только ASCII, кириллицу не трогает.
    Поэтому регистронезависимый поиск категорий делаем в Python через .lower(),
    а не через func.lower() в SQL-запросе.
"""
from sqlalchemy.orm import Session

from app.models import Product, Brand, Category


def seed_database(db: Session) -> None:
    """Наполняет БД тестовыми товарами, если она пустая."""
    if db.query(Product).count() > 0:
        return

    # ------------------------------------------------------------------
    # Кеш категорий: ключ — имя в нижнем регистре, значение — ORM-объект.
    # Один SELECT, дальше ищем в памяти. Дубликатов не будет.
    # ------------------------------------------------------------------
    cat_cache: dict[str, Category] = {
        c.name.lower(): c for c in db.query(Category).all()
    }

    def cat(name: str) -> Category:
        """Найти или создать категорию. Никогда не возвращает None."""
        key = name.strip().lower()
        if key in cat_cache:
            return cat_cache[key]
        c = Category(name=name.strip())
        db.add(c)
        db.flush()             # получаем id сразу, чтобы id попал в связку
        cat_cache[key] = c     # регистрируем в кеше — следующий вызов найдёт
        return c

    # ------------------------------------------------------------------
    # Базовый бренд (тоже идемпотентно, через кеш)
    # ------------------------------------------------------------------
    brand_cache = {b.name.lower(): b for b in db.query(Brand).all()}
    if "avelea" not in brand_cache:
        db.add(Brand(name="Avelea"))
        db.flush()

    # ------------------------------------------------------------------
    # Предсоздаём все категории заранее. Иначе cat() внутри списка
    # products ниже делает db.add() прямо во время конструирования
    # Product(...) — SQLAlchemy на это ругается SAWarning.
    # ------------------------------------------------------------------
    for cat_name in ("Очищение", "Уход", "Макияж"):
        cat(cat_name)

    # ------------------------------------------------------------------
    # Тестовые товары
    # ------------------------------------------------------------------
    products = [
        Product(
            name="Гидрофильное масло",
            categories=[cat("Очищение"), cat("Уход")],
            brand="Avelea",
            price=1290,
            popular=True,
            description="Нежное гидрофильное масло на основе натуральных растительных экстрактов.",
            volume="150 мл",
        ),
        Product(
            name="Сыворотка с витамином C",
            categories=[cat("Уход")],
            brand="Avelea",
            price=2450,
            popular=True,
            description="Концентрированная сыворотка с 15% стабильным витамином C.",
            volume="30 мл",
        ),
        Product(
            name="Увлажняющий крем",
            categories=[cat("Уход")],
            brand="Avelea",
            price=1890,
            popular=True,
            description="Лёгкий увлажняющий крем с комплексом из 5 типов гиалуроновой кислоты.",
            volume="50 мл",
        ),
        Product(
            name="SPF 50+ тональный",
            categories=[cat("Макияж"), cat("Уход")],
            brand="Avelea",
            price=1680,
            popular=False,
            description="Тональный крем с высокой солнцезащитой SPF 50+.",
            volume="40 мл",
        ),
        Product(
            name="Мицеллярная вода",
            categories=[cat("Очищение")],
            brand="Avelea",
            price=890,
            popular=False,
            description="Мягкая мицеллярная вода для бережного очищения.",
            volume="250 мл",
        ),
        Product(
            name="Бальзам для губ",
            categories=[cat("Уход")],
            brand="Avelea",
            price=450,
            popular=True,
            description="Питательный бальзам для губ с маслом ши и витамином E.",
            volume="4.5 г",
        ),
    ]

    db.add_all(products)
    db.commit()
    print("✅ База данных заполнена тестовыми товарами")