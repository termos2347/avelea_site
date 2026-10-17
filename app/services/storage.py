"""Абстракция хранилища медиафайлов (картинки + видео)."""
import hashlib
import io
import logging
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


def _read_limited(file, limit: int) -> tuple[bytes, bool]:
    chunks, total = [], 0
    while True:
        chunk = file.file.read(_READ_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            return b"", True
        chunks.append(chunk)
    return b"".join(chunks), False


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
    except (UnidentifiedImageError, OSError, ValueError):
        return None, None, "Файл повреждён или не является изображением."

    with Image.open(io.BytesIO(content)) as img:
        if img.format == "GIF":
            return content, ".gif", None
        if img.format == "WEBP" and (
            MAX_IMAGE_DIMENSION <= 0 or max(img.size) <= MAX_IMAGE_DIMENSION
        ):
            return content, ".webp", None

    try:
        with Image.open(io.BytesIO(content)) as img:
            if MAX_IMAGE_DIMENSION > 0 and max(img.size) > MAX_IMAGE_DIMENSION:
                img.thumbnail(
                    (MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION),
                    _RESAMPLE,
                )
            if img.mode not in ("RGB", "RGBA"):
                if img.mode in ("P", "LA") or "transparency" in img.info:
                    img = img.convert("RGBA")
                else:
                    img = img.convert("RGB")

            buf = io.BytesIO()
            img.save(buf, format="WEBP", quality=WEBP_QUALITY, method=WEBP_METHOD)
            return buf.getvalue(), ".webp", None
    except (OSError, ValueError) as e:
        log.warning("WebP-конвертация не удалась: %s", e)
        return None, None, "Не удалось обработать изображение."


class StorageBackend(ABC):
    @abstractmethod
    def save(self, content: bytes, ext: str, prefix: str = "") -> str: ...
    @abstractmethod
    def delete(self, filename: str) -> None: ...
    @abstractmethod
    def exists(self, filename: str) -> bool: ...
    @abstractmethod
    def public_url(self, filename: str) -> str: ...


def _make_filename(content: bytes, ext: str, prefix: str) -> str:
    """Собирает имя файла.

    С prefix: `<prefix>_<hash8><ext>` — например `about_hero_image_a1b2c3d4.webp`.
    Читаемо, кэш безопасен (хэш меняется → URL меняется).
    Без prefix: `<uuid><ext>` — для товаров (4 слота × N, ключ не подходит).
    """
    if prefix:
        h = hashlib.sha1(content).hexdigest()[:8]
        safe_prefix = "".join(
            c for c in prefix if c.isalnum() or c in "_-"
        )[:40]
        return f"{safe_prefix}_{h}{ext}"
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

    def save(self, content: bytes, ext: str, prefix: str = "") -> str:
        name = _make_filename(content, ext, prefix)
        content_type = {
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
        self.client.put_object(
            Bucket=self.bucket, Key=name,
            Body=content, ContentType=content_type,
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


_backend = _make_backend()


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
    content, too_large = _read_limited(file, limit)

    if too_large:
        mb = limit // (1024 * 1024)
        kind = "Видео" if is_vid else "Файл"
        return None, f"{kind} больше {mb} МБ — не сохранён."

    if not content:
        return None, None

    if is_vid:
        return _backend.save(content, ext), None

    new_content, new_ext, err = _optimize_image(content)
    if err is not None:
        return None, err

    return _backend.save(new_content, new_ext), None


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
_site_backend = LocalStorage(
    folder=BASE_DIR / "static" / "site",
    url_prefix="/static/site",
)


def save_site_image(file, key: str) -> tuple[str | None, str | None]:
    """Сохраняет картинку сайта с именем `<key>_<hash8>.webp`.

    key передаётся из роутера — например `about_hero_image`.
    Хэш от содержимого → браузер не закэширует старую версию.
    """
    if not file or not file.filename:
        return None, None

    head = file.file.read(16)
    if not head:
        return None, None

    ext, is_vid = _sniff_ext(head)
    if ext is None or is_vid:
        return None, "Поддерживаются только картинки: jpg, png, gif, webp."

    file.file.seek(0)

    content, too_large = _read_limited(file, MAX_UPLOAD_BYTES)
    if too_large:
        mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        return None, f"Файл больше {mb} МБ — не сохранён."
    if not content:
        return None, None

    new_content, new_ext, err = _optimize_image(content)
    if err is not None:
        return None, err

    return _site_backend.save(new_content, new_ext, prefix=key), None


def delete_site_image(filename: str | None) -> None:
    if filename:
        _site_backend.delete(filename)


def site_image_public_url(filename: str | None) -> str | None:
    if not filename:
        return None
    return _site_backend.public_url(filename)


def site_image_info(filename: str | None) -> dict | None:
    """Размер и путь файла — для отображения в админке."""
    if not filename:
        return None
    path = BASE_DIR / "static" / "site" / filename
    if not path.exists():
        return {"filename": filename, "size_kb": 0, "missing": True}
    size = path.stat().st_size
    return {
        "filename": filename,
        "size_kb": round(size / 1024, 1),
        "missing": False,
    }