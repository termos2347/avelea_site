"""Аудит целостности БД. Запускать перед выдачей доступа и после
крупных правок. Возвращает exit code 1, если что-то не так.

    python scripts/check_db.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.core.config import BASE_DIR
from app.core.database import SessionLocal, engine
from app.data.models import Product, Setting
from app.data.settings import SITE_CONTENT_KEYS


FAILED = []


def fail(msg: str) -> None:
    FAILED.append(msg)
    print(f"  ❌ {msg}")


def ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def check_migrations() -> None:
    print("\n[1] Миграции")
    cfg = Config(str(BASE_DIR / "alembic.ini"))
    head = ScriptDirectory.from_config(cfg).get_current_head()

    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()

    if current == head:
        ok(f"current == head == {current}")
    else:
        fail(f"current={current}, head={head} — БД отстаёт от схемы")

    heads = ScriptDirectory.from_config(cfg).get_heads()
    if len(heads) == 1:
        ok(f"одна голова: {heads[0]}")
    else:
        fail(f"несколько голов: {heads} — branched history, нужно merge")


def check_duplicates(db) -> None:
    print("\n[2] Дубликаты")

    dup_slug = db.execute(text(
        "SELECT slug, COUNT(*) FROM products "
        "WHERE slug IS NOT NULL GROUP BY slug HAVING COUNT(*) > 1"
    )).all()
    if dup_slug:
        fail(f"дубли slug: {dup_slug}")
    else:
        ok("slug уникальны")

    dup_brand = db.execute(text(
        "SELECT name, COUNT(*) FROM brands GROUP BY name HAVING COUNT(*) > 1"
    )).all()
    if dup_brand:
        fail(f"дубли brand.name: {dup_brand}")
    else:
        ok("brand.name уникальны")

    dup_cat = db.execute(text(
        "SELECT name, COUNT(*) FROM categories GROUP BY name HAVING COUNT(*) > 1"
    )).all()
    if dup_cat:
        fail(f"дубли category.name: {dup_cat}")
    else:
        ok("category.name уникальны")


def check_orphans(db) -> None:
    print("\n[3] Orphans (ссылки в никуда)")

    n = db.execute(text(
        "SELECT COUNT(*) FROM products p "
        "LEFT JOIN brands b ON p.brand_id = b.id "
        "WHERE p.brand_id IS NOT NULL AND b.id IS NULL"
    )).scalar()
    if n:
        fail(f"products.brand_id → несуществующий бренд: {n}")
    else:
        ok("products.brand_id ссылается на существующих брендов")

    n = db.execute(text(
        "SELECT COUNT(*) FROM product_variants v "
        "LEFT JOIN products p ON v.product_id = p.id "
        "WHERE p.id IS NULL"
    )).scalar()
    if n:
        fail(f"product_variants → несуществующий товар: {n}")
    else:
        ok("product_variants ссылается на существующих товаров")

    n = db.execute(text(
        "SELECT COUNT(*) FROM product_categories pc "
        "LEFT JOIN products p ON pc.product_id = p.id "
        "LEFT JOIN categories c ON pc.category_id = c.id "
        "WHERE p.id IS NULL OR c.id IS NULL"
    )).scalar()
    if n:
        fail(f"product_categories → битые ссылки: {n}")
    else:
        ok("product_categories целостна")


def check_name_lower(db) -> None:
    print("\n[4] Синхронизация name_lower")

    rows = db.query(Product.id, Product.name, Product.name_lower).all()
    bad = [
        (pid, name, nl)
        for pid, name, nl in rows
        if (nl or "") != (name or "").strip().lower()
    ]

    if bad:
        fail(f"name_lower рассинхронизирован у {len(bad)} товаров: {bad[:3]}...")
    else:
        ok(f"name_lower синхронизирован у всех товаров ({len(rows)})")


def check_slugs(db) -> None:
    print("\n[5] Slug")

    n = db.execute(text(
        "SELECT COUNT(*) FROM products WHERE slug IS NULL OR slug = ''"
    )).scalar()
    if n:
        fail(f"товаров без slug: {n}")
    else:
        ok("у всех товаров есть slug")


def check_prices(db) -> None:
    print("\n[6] Цены")

    n = db.execute(text("SELECT COUNT(*) FROM products WHERE price < 0")).scalar()
    if n:
        fail(f"товаров с отрицательной ценой: {n}")
    else:
        ok("все цены >= 0")

    n = db.execute(
        text("SELECT COUNT(*) FROM product_variants WHERE price < 0")
    ).scalar()
    if n:
        fail(f"вариантов с отрицательной ценой: {n}")
    else:
        ok("все цены вариантов >= 0")


def check_media_files(db) -> None:
    """Файлы, на которые ссылается БД, должны быть на диске."""
    print("\n[7] Медиафайлы на диске")

    from app.services.storage import _backend, _site_backend

    missing_products = []
    for p in db.query(Product).all():
        for f in (p.image, p.image_2, p.image_3, p.image_4):
            if f and not (_backend.folder / f).exists():
                missing_products.append((p.id, f))

    if missing_products:
        fail(f"products: {len(missing_products)} файлов отсутствует на диске")
        for pid, f in missing_products[:5]:
            print(f"     - product {pid}: {f}")
        if len(missing_products) > 5:
            print(f"     ... и ещё {len(missing_products) - 5}")
    else:
        ok("все картинки товаров на месте")

    # Проверяем только те ключи, которые реестр SITE_CONTENT_KEYS
    # считает картинками. Раньше было `key.endswith("_image")` —
    # это сломалось бы, если появится ключ вроде home_banner_bg
    # (без суффикса `_image`, но с типом image).
    missing_site = []
    for s in db.query(Setting).all():
        if SITE_CONTENT_KEYS.get(s.key, {}).get("type") != "image":
            continue
        if s.value and not (_site_backend.folder / s.value).exists():
            missing_site.append((s.key, s.value))

    if missing_site:
        fail(f"site: {len(missing_site)} файлов отсутствует на диске")
        for k, f in missing_site[:5]:
            print(f"     - {k}: {f}")
        if len(missing_site) > 5:
            print(f"     ... и ещё {len(missing_site) - 5}")
    else:
        ok("все картинки сайта на месте")


def check_orphan_files() -> None:
    """Файлы на диске, на которые не ссылается БД.

    Не ошибка, а сигнал. Удаляются автоматически при старте приложения
    (файлы старше 60 минут — защита от race с загрузкой).
    """
    print("\n[8] Orphan-файлы на диске")

    from app.services.storage import cleanup_orphans
    found = cleanup_orphans(min_age_minutes=0, dry_run=True)

    site_orphans = found["site"]
    upload_orphans = found["uploads"]

    if site_orphans:
        print(f"  ⚠️  static/site: {len(site_orphans)} файлов без ссылок в БД:")
        for f in site_orphans[:10]:
            print(f"     - {f}")
        if len(site_orphans) > 10:
            print(f"     ... и ещё {len(site_orphans) - 10}")
        print(f"     Удалятся при следующем рестарте сервера (lifespan).")
    else:
        ok("static/site: все файлы используются")

    if upload_orphans:
        print(f"  ⚠️  static/uploads: {len(upload_orphans)} файлов без ссылок в БД:")
        for f in upload_orphans[:10]:
            print(f"     - {f}")
        if len(upload_orphans) > 10:
            print(f"     ... и ещё {len(upload_orphans) - 10}")
        print(f"     Удалятся при следующем рестарте сервера (lifespan).")
    else:
        ok("static/uploads: все файлы используются")


def check_stats(db) -> None:
    print("\n[9] Статистика (не проверка, просто смотрим)")

    for label, q in [
        ("товаров всего",   "SELECT COUNT(*) FROM products"),
        ("из них активных", "SELECT COUNT(*) FROM products WHERE is_active"),
        ("популярных",      "SELECT COUNT(*) FROM products WHERE popular"),
        ("с картинкой",     "SELECT COUNT(*) FROM products WHERE image IS NOT NULL AND image != ''"),
        ("с вариантами",    "SELECT COUNT(DISTINCT product_id) FROM product_variants"),
        ("брендов",         "SELECT COUNT(*) FROM brands"),
        ("категорий",       "SELECT COUNT(*) FROM categories"),
        ("настроек",        "SELECT COUNT(*) FROM settings"),
    ]:
        v = db.execute(text(q)).scalar()
        print(f"     {label}: {v}")

    # Настроек с картинкой — через реестр SITE_CONTENT_KEYS, а не
    # через `key LIKE '%\_image' ESCAPE '\'`. Второе сломается, если
    # появится ключ картинки без суффикса `_image` (home_banner_bg).
    image_keys = [
        k for k, v in SITE_CONTENT_KEYS.items()
        if v.get("type") == "image"
    ]
    if image_keys:
        n = (
            db.query(Setting)
            .filter(
                Setting.key.in_(image_keys),
                Setting.value.isnot(None),
                Setting.value != "",
            )
            .count()
        )
    else:
        n = 0
    print(f"     настроек с картинкой: {n} из {len(image_keys)} возможных")


def main() -> int:
    print("=" * 60)
    print("Аудит БД Avelea")
    print("=" * 60)

    check_migrations()

    db = SessionLocal()
    try:
        check_duplicates(db)
        check_orphans(db)
        check_name_lower(db)
        check_slugs(db)
        check_prices(db)
        check_media_files(db)
        check_orphan_files()
        check_stats(db)
    finally:
        db.close()

    print("\n" + "=" * 60)
    if FAILED:
        print(f"❌ ПРОБЛЕМ: {len(FAILED)}")
        for m in FAILED:
            print(f"   - {m}")
        return 1
    print("✅ Всё в порядке")
    return 0


if __name__ == "__main__":
    sys.exit(main())