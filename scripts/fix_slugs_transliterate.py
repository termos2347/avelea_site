"""Одноразово: перегенерирует slug у товаров с «ю»/«ё» в названии.

Зачем: старые slug'и содержат «iu» и «e» от unidecode
(«Парфюм» → «parfium»). После фикса _slug_from_name новые товары
получают «yu»/«yo» («parfyum»), а старые остались с «iu»/«e».
Скрипт выравнивает их.

Идемпотентно: повторный запуск ничего не меняет.
Уже правильные slug'и не трогает.

Использование:
    python scripts/fix_slugs_transliterate.py
    python scripts/fix_slugs_transliterate.py --dry-run
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal
from app.data.models import Product, _slug_from_name
from app.data import cache


TRIGGER_CHARS = ("ю", "Ю", "ё", "Ё")


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    db = SessionLocal()
    try:
        rows = (
            db.query(Product)
            .filter(
                Product.name.contains("ю") | Product.name.contains("Ю")
                | Product.name.contains("ё") | Product.name.contains("Ё")
            )
            .all()
        )

        print(f"Найдено товаров с «ю»/«ё»: {len(rows)}")

        if not rows:
            print("Нечего исправлять.")
            return

        used = {
            s for (s,) in
            db.query(Product.slug).filter(Product.slug.isnot(None)).all()
        }

        changed = 0
        skipped = 0

        for p in rows:
            new_slug = _slug_from_name(p.name)
            if new_slug == p.slug:
                print(f"   {p.id}: {p.name!r} → {p.slug!r} (уже правильно)")
                continue

            if new_slug in used and new_slug != p.slug:
                print(f"   ⚠ {p.id}: {p.name!r} → {new_slug!r} занят, пропуск")
                skipped += 1
                continue

            print(f"   {p.id}: {p.name!r} → {p.slug!r} → {new_slug!r}")
            if not dry_run:
                used.discard(p.slug)
                used.add(new_slug)
                p.slug = new_slug
            changed += 1

        if not dry_run:
            db.commit()
            cache.invalidate()

        print()
        if dry_run:
            print(f"DRY-RUN: изменилось бы {changed}, коллизий {skipped}")
        else:
            print(f"✅ Обновлено: {changed}, коллизий: {skipped}")
    finally:
        db.close()


if __name__ == "__main__":
    main()