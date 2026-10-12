"""Заливает все картинки из static/uploads в S3.

Идемпотентно: файлы, которые уже в S3, пропускаются.
После успешного прогона в облаке лежат ВСЕ картинки из БД.

Запускать ДО переключения STORAGE_BACKEND=s3 (пока сайт ещё
работает через localhost — чтобы во время переноса картинки
были доступны).

Требует: pip install boto3, refactored storage.py (image = filename),
и миграцию migrate_urls_to_filenames.py (уже сделанную).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import boto3
from botocore.exceptions import ClientError

from app.core.config import (
    BASE_DIR,
    S3_ENDPOINT,
    S3_BUCKET,
    S3_ACCESS_KEY,
    S3_SECRET_KEY,
)
from app.core.database import SessionLocal
from app.data.models import Product


UPLOADS = BASE_DIR / "static" / "uploads"


def fail(msg: str) -> None:
    print(f"\n❌ {msg}")
    sys.exit(1)


def main():
    # ---- 0. Проверка конфига ----
    if not S3_BUCKET:
        fail("S3_BUCKET не задан в .env")
    if not S3_ACCESS_KEY or not S3_SECRET_KEY:
        fail("S3_ACCESS_KEY / S3_SECRET_KEY не заданы в .env")

    s3 = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT or None,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
    )

    # ---- 1. Что уже в S3 ----
    print(f"→ Читаю список файлов в бакете «{S3_BUCKET}»...")
    in_s3: set[str] = set()
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=S3_BUCKET):
            for obj in page.get("Contents", []):
                in_s3.add(obj["Key"])
    except ClientError as e:
        fail(f"Не могу прочитать бакет: {e}")

    print(f"  в S3 сейчас: {len(in_s3)} файлов")

    # ---- 2. Что должно быть (по БД) ----
    db = SessionLocal()
    products = db.query(Product).filter(Product.image.isnot(None)).all()
    db.close()

    names_db: set[str] = {p.image for p in products if p.image}
    print(f"  в БД у товаров: {len(names_db)} имён файлов")

    # ---- 3. Что есть локально ----
    if not UPLOADS.exists():
        fail(f"Папка {UPLOADS} не найдена")
    local_files: set[str] = {f.name for f in UPLOADS.iterdir() if f.is_file()}
    print(f"  локально в uploads: {len(local_files)} файлов")

    # ---- 4. Заливка ----
    print()
    uploaded = 0
    for name in sorted(names_db):
        if name in in_s3:
            continue
        local = UPLOADS / name
        if not local.exists():
            continue  # обработается в отчёте
        try:
            s3.upload_file(str(local), S3_BUCKET, name)
            in_s3.add(name)
            uploaded += 1
            print(f"  ↑ {name}")
        except ClientError as e:
            print(f"  ✗ {name}: {e}")

    # ---- 5. Отчёт ----
    missing_in_both = sorted(n for n in names_db if n not in in_s3)
    orphans = sorted(local_files - names_db)

    print()
    print("=" * 50)
    print(f"Уже было в S3:           {len(names_db) - uploaded - len(missing_in_both)}")
    print(f"Залито сейчас:           {uploaded}")
    print(f"Осталось не в S3:        {len(missing_in_both)}")
    print(f"Орфанов локально (нет в БД): {len(orphans)}")
    print("=" * 50)

    if missing_in_both:
        print()
        print("⚠  Эти имена из БД отсутствуют и в S3, и локально:")
        for name in missing_in_both:
            owners = [p for p in products if p.image == name]
            for p in owners:
                print(f"   товар {p.id}: {p.name}   (image={name!r})")
        print()
        print("   Возможно, файл был удалён вручную. Товар останется")
        print("   без картинки, но НИЧЕГО не сломается.")
    else:
        print()
        print("✅ Все картинки из БД гарантированно лежат в S3.")
        print("   Теперь можно переключить .env: STORAGE_BACKEND=s3")
        print("   и перезапустить сервер.")

    if orphans:
        print()
        print(f"ℹ  {len(orphans)} файлов лежат локально, но не привязаны")
        print("   к товарам (старые удалённые картинки). Их можно")
        print("   смело удалить вручную — они никому не нужны.")
        for name in orphans[:10]:
            print(f"   · {name}")
        if len(orphans) > 10:
            print(f"   … и ещё {len(orphans) - 10}")

    # Ненулевой код, если что-то реально потеряно
    if missing_in_both:
        sys.exit(2)


if __name__ == "__main__":
    main()