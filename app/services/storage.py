"""Абстракция хранилища картинок.

В БД лежит ТОЛЬКО имя файла ("abc123.jpg"), без пути и домена.
Публичный URL собирается здесь, под текущий бэкенд — поэтому
переключение local↔S3 не требует правки БД.
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
# Валидация и оптимизация картинок
# ============================================================
_MAGIC = (
    (b"\xff\xd8\xff",      ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"GIF87a",            ".gif"),
    (b"GIF89a",            ".gif"),
)
_ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "GIF", "WEBP"}
_READ_CHUNK = 64 * 1024

_RESAMPLE = (
    Image.Resampling.LANCZOS
    if hasattr(Image, "Resampling")
    else Image.LANCZOS
)


def _sniff_image_ext(head: bytes) -> str | None:
    for magic, ext in _MAGIC:
        if head.startswith(magic):
            return ext
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    return None


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
# Все методы работают с ИМЕНЕМ ФАЙЛА, не с URL.
# ============================================================
class StorageBackend(ABC):
    @abstractmethod
    def save(self, content: bytes, ext: str) -> str:
        """Сохраняет байты, возвращает имя файла."""

    @abstractmethod
    def delete(self, filename: str) -> None:
        """Удаляет файл по имени."""

    @abstractmethod
    def exists(self, filename: str) -> bool:
        """Есть ли файл в хранилище."""

    @abstractmethod
    def public_url(self, filename: str) -> str:
        """Публичный URL для имени файла."""


# ============================================================
# Локальное хранилище
# ============================================================
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


# ============================================================
# S3 / MinIO / R2
# ============================================================
class S3Storage(StorageBackend):
    def __init__(self, endpoint, bucket, access_key, secret_key, base_url):
        try:
            import boto3
        except ImportError:
            raise RuntimeError(
                "STORAGE_BACKEND=s3, но boto3 не установлен. "
                "Выполни: pip install boto3"
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
        self.client.put_object(
            Bucket=self.bucket,
            Key=name,
            Body=content,
            ContentType="image/" + ext.lstrip("."),
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


# ============================================================
# Фабрика
# ============================================================
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
def save_image(file) -> tuple[str | None, str | None]:
    """Сохраняет картинку. Возвращает (filename, error).

    - (filename, None) — успех;
    - (None, None)     — файла не было / пустой (не ошибка);
    - (None, "...")    — отклонён с причиной.
    """
    if not file or not file.filename:
        return None, None

    content, too_large = _read_limited(file, MAX_UPLOAD_BYTES)
    if too_large:
        return None, (
            f"Файл больше {MAX_UPLOAD_BYTES // (1024 * 1024)} МБ — "
            "картинка не сохранена."
        )
    if not content:
        return None, None

    ext = _sniff_image_ext(content[:16])
    if ext is None:
        return None, (
            "Формат не поддерживается (разрешены jpg, png, gif, webp) — "
            "картинка не сохранена."
        )

    content, err = _optimize_image(content)
    if err is not None:
        return None, err

    return _backend.save(content, ext), None


def delete_image(filename: str | None) -> None:
    if filename:
        _backend.delete(filename)


def public_url(filename: str | None) -> str | None:
    """Собирает публичный URL из имени файла. None → None."""
    if not filename:
        return None
    return _backend.public_url(filename)


def file_exists(filename: str | None) -> bool:
    """Проверяет наличие файла в текущем хранилище."""
    if not filename:
        return False
    return _backend.exists(filename)