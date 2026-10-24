"""Абстракция хранилища медиафайлов (картинки + видео)."""
import hashlib
import io
import logging
import shutil
import tempfile
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.core.config import (
    BASE_DIR,
    MAX_UPLOAD_BYTES,
    MAX_VIDEO_UPLOAD_BYTES,
    MAX_IMAGE_DIMENSION,
    STORAGE_BACKEND,
    S3_ENDPOINT,
    S3_BUCKET,
    S3_ACCESS_KEY,
    S3_SECRET_KEY,
    S3_PUBLIC_URL,
)

log = logging.getLogger(__name__)


WEBP_QUALITY = 85
WEBP_METHOD = 6


_MAGIC = (
    (b"\xff\xd8\xff",          ".jpg"),
    (b"\x89PNG\r\n\x1a\n",     ".png"),
    (b"GIF87a",                ".gif"),
    (b"GIF89a",                ".gif"),
    (b"\x1a\x45\xdf\xa3",      ".webm"),
)

_VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v"}
_ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "GIF", "WEBP"}
_READ_CHUNK = 64 * 1024
_SPOOL_MAX = 1024 * 1024  # 1 МБ в RAM, дальше — на диск

_PIL_OPEN_ERRORS = (
    UnidentifiedImageError,
    OSError,
    ValueError,
    Image.DecompressionBombError,
)

_RESAMPLE = (
    Image.Resampling.LANCZOS
    if hasattr(Image, "Resampling")
    else Image.LANCZOS
)


def _sniff_ext(head: bytes) -> tuple[str | None, bool]:
    for magic, ext in _MAGIC:
        if head.startswith(magic):
            return ext, ext in _VIDEO_EXTS
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp", False
    if len(head) >= 12 and head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand == b"qt  ":
            return ".mov", True
        return ".mp4", True
    return None, False


def is_video(filename: str | None) -> bool:
    if not filename:
        return False
    return Path(filename).suffix.lower() in _VIDEO_EXTS


def _stream_to_spooled(file, limit: int) -> tuple[tempfile.SpooledTemporaryFile | None, bool]:
    spooled = tempfile.SpooledTemporaryFile(max_size=_SPOOL_MAX, mode="w+b")
    total = 0
    try:
        while True:
            chunk = file.file.read(_READ_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                spooled.close()
                return None, True
            spooled.write(chunk)
        spooled.seek(0)
        return spooled, False
    except Exception:
        spooled.close()
        raise


def _optimize_image(content: bytes) -> tuple[bytes | None, str | None, str | None]:
    try:
        with Image.open(io.BytesIO(content)) as img:
            fmt = img.format
            if fmt not in _ALLOWED_IMAGE_FORMATS:
                return None, None, (
                    f"Формат {fmt or '?'} не поддерживается "
                    "(разрешены jpg, png, gif, webp) — файл не сохранён."
                )
            img.verify()
    except _PIL_OPEN_ERRORS:
        return None, None, "Файл повреждён или не является изображением."

    try:
        with Image.open(io.BytesIO(content)) as img:
            if img.format == "GIF":
                return content, ".gif", None
            if img.format == "WEBP" and (
                MAX_IMAGE_DIMENSION <= 0 or max(img.size) <= MAX_IMAGE_DIMENSION
            ):
                return content, ".webp", None
    except _PIL_OPEN_ERRORS:
        return None, None, "Файл повреждён или не является изображением."

    try:
        with Image.open(io.BytesIO(content)) as img:
            if MAX_IMAGE_DIMENSION > 0 and max(img.size) > MAX_IMAGE_DIMENSION:
                img.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), _RESAMPLE)
            if img.mode not in ("RGB", "RGBA"):
                if img.mode in ("P", "LA") or "transparency" in img.info:
                    img = img.convert("RGBA")
                else:
                    img = img.convert("RGB")

            buf = io.BytesIO()
            img.save(buf, format="WEBP", quality=WEBP_QUALITY, method=WEBP_METHOD)
            return buf.getvalue(), ".webp", None
    except _PIL_OPEN_ERRORS as e:
        log.warning("WebP-конвертация не удалась: %s", e)
        return None, None, "Не удалось обработать изображение."


def _hash_stream(spooled) -> tuple[str, int]:
    h = hashlib.sha1()
    size = 0
    while True:
        chunk = spooled.read(_READ_CHUNK)
        if not chunk:
            break
        h.update(chunk)
        size += len(chunk)
    spooled.seek(0)
    return h.hexdigest(), size


def _safe_prefix(prefix: str) -> str:
    return "".join(c for c in prefix if c.isalnum() or c in "_-")[:40]


def _make_stream_filename(spooled, ext: str, prefix: str) -> tuple[str, int]:
    if prefix:
        hex_hash, size = _hash_stream(spooled)
        return f"{_safe_prefix(prefix)}_{hex_hash[:8]}{ext}", size
    size = 0
    while True:
        chunk = spooled.read(_READ_CHUNK)
        if not chunk:
            break
        size += len(chunk)
    spooled.seek(0)
    return f"{uuid.uuid4().hex}{ext}", size


class StorageBackend(ABC):
    @abstractmethod
    def save(self, content: bytes, ext: str, prefix: str = "") -> str: ...
    @abstractmethod
    def save_stream(self, spooled, ext: str, prefix: str = "") -> str: ...
    @abstractmethod
    def delete(self, filename: str) -> None: ...
    @abstractmethod
    def exists(self, filename: str) -> bool: ...
    @abstractmethod
    def public_url(self, filename: str) -> str: ...
    @abstractmethod
    def stat(self, filename: str) -> dict | None:
        """Информация о файле.

        Возвращает dict с ключами:
          - filename: str
          - size_kb: float
          - missing: bool — True если файла нет
          - modified_ts: float | None — Unix-время модификации
                                        (None если бэкенд не умеет)

        Возвращает None, если произошла ошибка доступа/сети
        (не путать с missing=True — тот случай значит «файла нет»).
        """
        ...
    @abstractmethod
    def list_files(self) -> list[str]:
        """Возвращает имена всех файлов в хранилище."""
        ...


def _make_filename(content: bytes, ext: str, prefix: str) -> str:
    if prefix:
        h = hashlib.sha1(content).hexdigest()[:8]
        return f"{_safe_prefix(prefix)}_{h}{ext}"
    return f"{uuid.uuid4().hex}{ext}"


class LocalStorage(StorageBackend):
    def __init__(self, folder: Path, url_prefix: str):
        self.folder = folder
        self.url_prefix = url_prefix
        self.folder.mkdir(parents=True, exist_ok=True)

    def save(self, content: bytes, ext: str, prefix: str = "") -> str:
        name = _make_filename(content, ext, prefix)
        (self.folder / name).write_bytes(content)
        return name

    def save_stream(self, spooled, ext: str, prefix: str = "") -> str:
        name, _ = _make_stream_filename(spooled, ext, prefix)
        with open(self.folder / name, "wb") as out:
            shutil.copyfileobj(spooled, out, length=_READ_CHUNK)
        return name

    def delete(self, filename: str) -> None:
        if not filename or "/" in filename or ".." in filename:
            return
        try:
            (self.folder / filename).unlink(missing_ok=True)
        except OSError as e:
            log.warning("Не удалось удалить %s: %s", filename, e)

    def exists(self, filename: str) -> bool:
        if not filename or "/" in filename or ".." in filename:
            return False
        return (self.folder / filename).exists()

    def public_url(self, filename: str) -> str:
        return f"{self.url_prefix}/{filename}"

    def stat(self, filename: str) -> dict | None:
        if not filename or "/" in filename or ".." in filename:
            return None
        path = self.folder / filename
        try:
            st = path.stat()
        except FileNotFoundError:
            return {
                "filename": filename,
                "size_kb": 0,
                "missing": True,
                "modified_ts": None,
            }
        except OSError as e:
            log.warning("Не удалось получить stat %s: %s", filename, e)
            return None
        return {
            "filename": filename,
            "size_kb": round(st.st_size / 1024, 1),
            "missing": False,
            "modified_ts": st.st_mtime,
        }

    def list_files(self) -> list[str]:
        if not self.folder.exists():
            return []
        return [
            f.name for f in self.folder.iterdir() if f.is_file()
        ]


class S3Storage(StorageBackend):
    def __init__(self, endpoint, bucket, access_key, secret_key, base_url):
        try:
            import boto3
        except ImportError:
            raise RuntimeError("STORAGE_BACKEND=s3, но boto3 не установлен.")
        self.bucket = bucket
        self.base_url = (base_url or "").rstrip("/")
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint or None,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    @staticmethod
    def _content_type(ext: str) -> str:
        return {
            ".mp4":  "video/mp4",
            ".webm": "video/webm",
            ".mov":  "video/quicktime",
            ".m4v":  "video/x-m4v",
            ".jpg":  "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png":  "image/png",
            ".gif":  "image/gif",
            ".webp": "image/webp",
        }.get(ext, "application/octet-stream")

    def save(self, content: bytes, ext: str, prefix: str = "") -> str:
        name = _make_filename(content, ext, prefix)
        self.client.put_object(
            Bucket=self.bucket, Key=name,
            Body=content, ContentType=self._content_type(ext),
        )
        return name

    def save_stream(self, spooled, ext: str, prefix: str = "") -> str:
        name, _ = _make_stream_filename(spooled, ext, prefix)
        self.client.upload_fileobj(
            spooled, self.bucket, name,
            ExtraArgs={"ContentType": self._content_type(ext)},
        )
        return name

    def delete(self, filename: str) -> None:
        if not filename or "/" in filename or ".." in filename:
            return
        try:
            self.client.delete_object(Bucket=self.bucket, Key=filename)
        except Exception as e:
            log.warning("Не удалось удалить %s из S3: %s", filename, e)

    def exists(self, filename: str) -> bool:
        if not filename or "/" in filename or ".." in filename:
            return False
        try:
            self.client.head_object(Bucket=self.bucket, Key=filename)
            return True
        except Exception:
            return False

    def public_url(self, filename: str) -> str:
        return f"{self.base_url}/{filename}"

    def stat(self, filename: str) -> dict | None:
        if not filename or "/" in filename or ".." in filename:
            return None
        try:
            resp = self.client.head_object(Bucket=self.bucket, Key=filename)
        except Exception as e:
            # boto3 на 404 отдаёт ClientError с кодом в .response
            resp_err = getattr(e, "response", None) or {}
            code = str(resp_err.get("Error", {}).get("Code", ""))
            if code in ("404", "NoSuchKey", "NotFound"):
                return {
                    "filename": filename,
                    "size_kb": 0,
                    "missing": True,
                    "modified_ts": None,
                }
            log.warning("S3 stat failed для %s: %s", filename, e)
            return None

        size = resp.get("ContentLength", 0)
        last_mod = resp.get("LastModified")
        modified_ts = last_mod.timestamp() if last_mod else None
        return {
            "filename": filename,
            "size_kb": round(size / 1024, 1),
            "missing": False,
            "modified_ts": modified_ts,
        }

    def list_files(self) -> list[str]:
        result: list[str] = []
        try:
            paginator = self.client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket):
                for obj in page.get("Contents", []):
                    result.append(obj["Key"])
        except Exception as e:
            log.warning("S3 list_files failed: %s", e)
        return result


def _make_backend() -> StorageBackend:
    if STORAGE_BACKEND == "s3":
        return S3Storage(
            endpoint=S3_ENDPOINT,
            bucket=S3_BUCKET,
            access_key=S3_ACCESS_KEY,
            secret_key=S3_SECRET_KEY,
            base_url=S3_PUBLIC_URL,
        )
    return LocalStorage(
        folder=BASE_DIR / "static" / "uploads",
        url_prefix="/static/uploads",
    )


def _make_site_backend() -> StorageBackend:
    """Тот же выбор бэкенда, что и для товаров.

    Если STORAGE_BACKEND=s3 — контентные картинки сайта тоже идут в S3.
    Для витрины на одном сервере — local.
    """
    if STORAGE_BACKEND == "s3":
        return S3Storage(
            endpoint=S3_ENDPOINT,
            bucket=S3_BUCKET,
            access_key=S3_ACCESS_KEY,
            secret_key=S3_SECRET_KEY,
            base_url=S3_PUBLIC_URL,
        )
    return LocalStorage(
        folder=BASE_DIR / "static" / "site",
        url_prefix="/static/site",
    )


_backend = _make_backend()
_site_backend = _make_site_backend()


# ============================================================
# Товары
# ============================================================
def save_media(file) -> tuple[str | None, str | None]:
    if not file or not file.filename:
        return None, None

    head = file.file.read(16)
    if not head:
        return None, None

    ext, is_vid = _sniff_ext(head)
    if ext is None:
        return None, (
            "Формат не поддерживается (картинки: jpg, png, gif, webp; "
            "видео: mp4, webm, mov) — файл не сохранён."
        )

    file.file.seek(0)

    limit = MAX_VIDEO_UPLOAD_BYTES if is_vid else MAX_UPLOAD_BYTES
    spooled, too_large = _stream_to_spooled(file, limit)

    if too_large:
        mb = limit // (1024 * 1024)
        kind = "Видео" if is_vid else "Файл"
        return None, f"{kind} больше {mb} МБ — не сохранён."

    try:
        if is_vid:
            return _backend.save_stream(spooled, ext), None

        content = spooled.read()
        if not content:
            return None, None
        new_content, new_ext, err = _optimize_image(content)
        if err is not None:
            return None, err
        return _backend.save(new_content, new_ext), None
    finally:
        spooled.close()


def delete_media(filename: str | None) -> None:
    if filename:
        _backend.delete(filename)


def public_url(filename: str | None) -> str | None:
    if not filename:
        return None
    return _backend.public_url(filename)


def file_exists(filename: str | None) -> bool:
    if not filename:
        return False
    return _backend.exists(filename)


save_image = save_media
delete_image = delete_media


# ============================================================
# Картинки сайта (about, hero и т.п.)
# ============================================================
def save_site_image(file, key: str) -> tuple[str | None, str | None]:
    if not file or not file.filename:
        return None, None

    head = file.file.read(16)
    if not head:
        return None, None

    ext, is_vid = _sniff_ext(head)
    if ext is None or is_vid:
        return None, "Поддерживаются только картинки: jpg, png, gif, webp."

    file.file.seek(0)

    spooled, too_large = _stream_to_spooled(file, MAX_UPLOAD_BYTES)
    if too_large:
        mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        return None, f"Файл больше {mb} МБ — не сохранён."

    try:
        content = spooled.read()
        if not content:
            return None, None
        new_content, new_ext, err = _optimize_image(content)
        if err is not None:
            return None, err
        return _site_backend.save(new_content, new_ext, prefix=key), None
    finally:
        spooled.close()


def delete_site_image(filename: str | None) -> None:
    if filename:
        _site_backend.delete(filename)


def site_image_public_url(filename: str | None) -> str | None:
    if not filename:
        return None
    return _site_backend.public_url(filename)


def site_image_info(filename: str | None) -> dict | None:
    if not filename:
        return None
    return _site_backend.stat(filename)


# ============================================================
# Очистка orphan-файлов
# ============================================================
def cleanup_orphans(min_age_minutes: int = 60, dry_run: bool = True) -> dict:
    """Удаляет файлы на диске, на которые нет ссылок в БД.

    Орфаны появляются, когда:
      - замена картинки через админку упала между save и commit;
      - старый файл не удалился из-за OSError (readonly FS, права);
      - ручное вмешательство в БД.

    Работает через StorageBackend.list_files/stat/delete — подходит
    и для local, и для S3.

    Параметры:
      min_age_minutes — не трогать файлы младше N минут. Защита от
                        race: только что загруженная картинка может
                        быть ещё не привязана (между save и commit).
      dry_run         — True: только найти, не удалять.

    ВНИМАНИЕ: для referenced_site критерий — s.key.endswith("_image").
    Если добавите ключ картинки с другим суффиксом (_banner, _photo),
    он попадёт в orphans и будет удалён. Расширьте условие ниже.
    """
    import time
    from app.core.database import SessionLocal
    from app.data.models import Product, Setting

    db = SessionLocal()
    try:
        referenced_site = {
            s.value for s in db.query(Setting).all()
            if s.key and s.key.endswith("_image") and s.value
        }
        referenced_uploads = set()
        for p in db.query(Product).all():
            for f in (p.image, p.image_2, p.image_3, p.image_4):
                if f:
                    referenced_uploads.add(f)
    finally:
        db.close()

    cutoff = time.time() - min_age_minutes * 60

    result: dict[str, list[str]] = {"site": [], "uploads": []}

    for backend, refs, kind in (
        (_site_backend, referenced_site, "site"),
        (_backend, referenced_uploads, "uploads"),
    ):
        for name in backend.list_files():
            if name in refs:
                continue

            info = backend.stat(name)
            if info is not None and not info.get("missing"):
                modified_ts = info.get("modified_ts")
                if modified_ts is not None and modified_ts > cutoff:
                    # Свежий файл — пропускаем (защита от race).
                    continue

            result[kind].append(name)

            if not dry_run:
                try:
                    backend.delete(name)
                except Exception as e:
                    log.warning("cleanup_orphans: не удалось удалить %s: %s", name, e)

    result["site"].sort()
    result["uploads"].sort()
    return result