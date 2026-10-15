"""Абстракция хранилища медиафайлов (картинки + видео).

В БД лежит ТОЛЬКО имя файла ("abc123.jpg" или "video.mp4").
Публичный URL собирается здесь, под текущий бэкенд — поэтому
переключение local↔S3 не требует правки БД.

Картинки: валидируются через Pillow, ресайзятся до MAX_IMAGE_DIMENSION.
Видео: только проверка magic bytes и размера, сохраняются как есть.
"""
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


# ============================================================
# Определение типа файла по magic bytes
# ============================================================
_MAGIC = (
    # --- Картинки ---
    (b"\xff\xd8\xff",          ".jpg"),
    (b"\x89PNG\r\n\x1a\n",     ".png"),
    (b"GIF87a",                ".gif"),
    (b"GIF89a",                ".gif"),
    # --- Видео ---
    # MP4 и MOV: [size:4] ftyp. Точный бренд не важен, берём первые 8 байт.
    # WebM/Matroska: EBML header.
    (b"\x1a\x45\xdf\xa3",      ".webm"),
)
_VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v", ".ogv"}
_ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "GIF", "WEBP"}
_READ_CHUNK = 64 * 1024

_RESAMPLE = (
    Image.Resampling.LANCZOS
    if hasattr(Image, "Resampling")
    else Image.LANCZOS
)


def _sniff_ext(head: bytes) -> tuple[str | None, bool]:
    """Определяет расширение и является ли файл видео.

    Возвращает (ext, is_video):
      ('.jpg', False), ('.mp4', True), (None, False) — если не распознали.
    """
    for magic, ext in _MAGIC:
        if head.startswith(magic):
            return ext, ext in _VIDEO_EXTS

    # WEBP: RIFF....WEBP
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp", False

    # MP4/MOV: байты 4-8 == 'ftyp'
    if len(head) >= 12 and head[4:8] == b"ftyp":
        # Бренд в байтах 8-12: isom, mp42, M4V, qt и т.п.
        brand = head[8:12]
        if brand in (b"qt  ",):
            return ".mov", True
        return ".mp4", True

    return None, False


def is_video(filename: str | None) -> bool:
    """True, если имя файла соответствует видео-формату."""
    if not filename:
        return False
    ext = Path(filename).suffix.lower()
    return ext in _VIDEO_EXTS


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


def _optimize_image(content: bytes) -> tuple[bytes | None, str | None]:
    try:
        with Image.open(io.BytesIO(content)) as img:
            fmt = img.format
            if fmt not in _ALLOWED_IMAGE_FORMATS:
                return None, (
                    f"Формат {fmt or '?'} не поддерживается "
                    "(разрешены jpg, png, gif, webp) — картинка не сохранена."
                )
            img.verify()
    except (UnidentifiedImageError, OSError, ValueError):
        return None, (
            "Файл повреждён или не является изображением — "
            "картинка не сохранена."
        )

    if MAX_IMAGE_DIMENSION <= 0:
        return content, None

    try:
        with Image.open(io.BytesIO(content)) as img:
            fmt = img.format
            if fmt == "GIF":
                return content, None
            if max(img.size) <= MAX_IMAGE_DIMENSION:
                return content, None

            img.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), _RESAMPLE)
            buf = io.BytesIO()
            if fmt == "PNG":
                img.save(buf, format="PNG", optimize=True)
            elif fmt == "WEBP":
                img.save(buf, format="WEBP", quality=85, method=6)
            else:
                if img.mode in ("RGBA", "P", "LA"):
                    img = img.convert("RGB")
                img.save(buf, format="JPEG", quality=85, optimize=True)
            return buf.getvalue(), None
    except (OSError, ValueError) as e:
        log.warning("Ресайз не удался, сохраняем оригинал: %s", e)
        return content, None


# ============================================================
# Интерфейс бэкенда
# ============================================================
class StorageBackend(ABC):
    @abstractmethod
    def save(self, content: bytes, ext: str) -> str: ...
    @abstractmethod
    def delete(self, filename: str) -> None: ...
    @abstractmethod
    def exists(self, filename: str) -> bool: ...
    @abstractmethod
    def public_url(self, filename: str) -> str: ...


class LocalStorage(StorageBackend):
    def __init__(self, folder: Path, url_prefix: str):
        self.folder = folder
        self.url_prefix = url_prefix
        self.folder.mkdir(parents=True, exist_ok=True)

    def save(self, content: bytes, ext: str) -> str:
        name = f"{uuid.uuid4().hex}{ext}"
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
            raise RuntimeError(
                "STORAGE_BACKEND=s3, но boto3 не установлен."
            )
        self.bucket = bucket
        self.base_url = (base_url or "").rstrip("/")
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint or None,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    def save(self, content: bytes, ext: str) -> str:
        name = f"{uuid.uuid4().hex}{ext}"
        content_type = {
            ".mp4": "video/mp4",
            ".webm": "video/webm",
            ".mov": "video/quicktime",
            ".m4v": "video/x-m4v",
            ".ogv": "video/ogg",
        }.get(ext, "application/octet-stream")
        if ext in (".jpg", ".jpeg"):
            content_type = "image/jpeg"
        elif ext == ".png":
            content_type = "image/png"
        elif ext == ".gif":
            content_type = "image/gif"
        elif ext == ".webp":
            content_type = "image/webp"

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
# Публичный API
# ============================================================
def save_media(file) -> tuple[str | None, str | None]:
    """Сохраняет картинку или видео. Возвращает (filename, error)."""
    if not file or not file.filename:
        return None, None

    # Сначала читаем первые байты, чтобы понять тип.
    head = file.file.read(16)
    if not head:
        return None, None

    ext, is_vid = _sniff_ext(head)
    if ext is None:
        return None, (
            "Формат не поддерживается (картинки: jpg, png, gif, webp; "
            "видео: mp4, webm, mov) — файл не сохранён."
        )

    # Возвращаем голову обратно в поток.
    file.file.seek(0)

    # Читаем весь файл с лимитом под тип.
    limit = MAX_VIDEO_UPLOAD_BYTES if is_vid else MAX_UPLOAD_BYTES
    content, too_large = _read_limited(file, limit)

    if too_large:
        mb = limit // (1024 * 1024)
        kind = "Видео" if is_vid else "Файл"
        return None, f"{kind} больше {mb} МБ — не сохранён."

    if not content:
        return None, None

    if is_vid:
        # Видео — сохраняем как есть.
        return _backend.save(content, ext), None

    # Картинка — оптимизируем.
    content, err = _optimize_image(content)
    if err is not None:
        return None, err

    return _backend.save(content, ext), None


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