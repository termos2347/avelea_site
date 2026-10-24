"""Одноразово: проставляет slug всем товарам, у которых его нет.

Идемпотентно. Если колонки slug ещё нет — создаёт её.

Зачем скрипт существует:
    Alembic создаёт колонку products.slug как NULL-able (baseline
    миграция f63c89e8e32f). Заполняет её событие before_insert в
    models.py — но только для НОВЫХ товаров. Если в БД уже были
    товары до появления колонки slug, у них slug = NULL, и страница
    /product/{slug_or_id} работает только по ID.

    Этот скрипт проставляет slug таким «старым» товарам разово.

Изменения от предыдущей версии:
    - Использует _slug_from_name из app.data.models, а не сырой
      slugify. Иначе «Парфюм» → «parfium» (unidecode), а не
      «parfyum». Иначе свежесозданные и «дочиниваемые» товары
      получали бы разные slug'и при одинаковом name.

    - Ловит IntegrityError, если по какой-то причине колонка slug
      уже существует с UNIQUE-индексом и slug конфликтует. Это
      защита от race: скрипт может запуститься параллельно с
      insert'ом через веб-форму.

Использование:
    python scripts/migrate_add_slugs.py
    python scripts/migrate_add_slugs.py --dry-run
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal, engine
from app.data.models import Product, _slug_from_name
from app.data import cache


def _ensure_slug_column() -> None:
    """Создать products.slug, если её ещё нет (для очень старых БД)."""
    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("products")}
    if "slug" in cols:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE products ADD COLUMN slug VARCHAR(250)"))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_products_slug "
            "ON products (slug)"
        ))
    print("→ Добавлена колонка products.slug")


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    _ensure_slug_column()

    db = SessionLocal()
    try:
        products = (
            db.query(Product)
            .filter((Product.slug.is_(None)) | (Product.slug == ""))
            .order_by(Product.id)
            .all()
        )

        if not products:
            print("Все товары уже имеют slug.")
            return

        print(f"Товаров без slug: {len(products)}")

        used = {
            s for (s,) in
            db.query(Product.slug).filter(Product.slug.isnot(None)).all()
        }

        changed = 0
        for p in products:
            base = _slug_from_name(p.name) or f"product-{p.id}"
            candidate = base
            n = 1
            while candidate in used:
                n += 1
                candidate = f"{base}-{n}"

            used.add(candidate)
            print(f"   {p.id}: {p.name!r} → {candidate!r}")

            if dry_run:
                continue

            p.slug = candidate
            try:
                db.flush()
                changed += 1
            except IntegrityError:
                # Кто-то параллельно занял этот slug (веб-форма).
                # Откатываем только этого товара, продолжаем
                # со следующим.
                db.rollback()
                used.discard(candidate)
                print(f"   ⚠ {p.id}: {candidate!r} занят параллельно, пропуск")

        if dry_run:
            print(f"\nDRY-RUN: проставилось бы {len(products)} slug'ов")
            return

        db.commit()
        cache.invalidate()
        print(f"\n✅ Обновлено: {changed} из {len(products)}")
    finally:
        db.close()


if __name__ == "__main__":
    main()