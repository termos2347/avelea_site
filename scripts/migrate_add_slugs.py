"""Одноразово: проставляет slug всем товарам, у которых его нет.

Идемпотентно. Если колонки slug ещё нет — создаёт её.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from slugify import slugify
from sqlalchemy import inspect, text

from app.core.database import SessionLocal, engine
from app.data.models import Product


def _ensure_slug_column():
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


def main():
    _ensure_slug_column()

    db = SessionLocal()
    products = db.query(Product).filter(
        (Product.slug.is_(None)) | (Product.slug == "")
    ).all()

    if not products:
        print("Все товары уже имеют slug.")
        db.close()
        return

    used = {
        s for (s,) in db.query(Product.slug).filter(Product.slug.isnot(None)).all()
    }

    for p in products:
        base = slugify(p.name, max_length=200, word_boundary=True) or f"product-{p.id}"
        candidate = base
        n = 1
        while candidate in used:
            n += 1
            candidate = f"{base}-{n}"
        used.add(candidate)
        p.slug = candidate
        print(f"   {p.id}: {p.name!r} → {candidate}")

    db.commit()
    db.close()
    print(f"\nОбработано: {len(products)}")


if __name__ == "__main__":
    main()