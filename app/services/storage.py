"""Абстракция хранилища картинок.

Сейчас работает с локальной папкой, но интерфейс готов к S3.
Чтобы переехать на S3 — поменяй STORAGE_BACKEND в .env, код
приложения трогать не нужно.
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
    STORAGE_BACKEND,
    S3_ENDPOINT,
    S3_BUCKET,
    S3_ACCESS_KEY,
    S3_SECRET_KEY,
    S3_PUBLIC_URL,
)

log = logging.getLogger(__name__)


# ============================================================
# Общий код: валидация картинок (одинаков для всех бэкендов)
# ============================================================
_MAGIC = (
    (b"\xff\xd8\xff",          ".jpg"),
    (b"\x89PNG\r\n\x1a\n",     ".png"),
    (b"GIF87a",                ".gif"),
    (b"GIF89a",                ".gif"),
)
_ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "GIF", "WEBP"}
_READ_CHUNK = 64 * 1024


def _sniff_image_ext(head: bytes) -> str | None:
    for magic, ext in _MAGIC:
        if head.startswith(magic):
            return ext
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    return None


def _read_limited(file, limit: int) -> tuple[bytes, bool]:
    chunks = []
    total = 0
    while True:
        chunk = file.file.read(_READ_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            return b"", True
        chunks.append(chunk)
    return b"".join(chunks), False


def _verify_image(content: bytes) -> str | None:
    try:
        img = Image.open(io.BytesIO(content))
        if img.format not in _ALLOWED_IMAGE_FORMATS:
            return (
                f"Формат {img.format or '?'} не поддерживается "
                "(разрешены jpg, png, gif, webp) — картинка не сохранена."
            )
        img.verify()
    except (UnidentifiedImageError, OSError, ValueError):
        return "Файл повреждён или не является изображением — картинка не сохранена."
    return None


# ============================================================
# Интерфейс бэкенда
# ============================================================
class StorageBackend(ABC):
    @abstractmethod
    def save(self, content: bytes, ext: str) -> str:
        """Сохраняет файл и возвращает публичный URL."""

    @abstractmethod
    def delete(self, url: str) -> None:
        """Удаляет файл по публичному URL."""


# ============================================================
# Локальная папка
# ============================================================
class LocalStorage(StorageBackend):
    def __init__(self, folder: Path, url_prefix: str):
        self.folder = folder
        self.url_prefix = url_prefix
        self.folder.mkdir(parents=True, exist_ok=True)

    def save(self, content: bytes, ext: str) -> str:
        name = f"{uuid.uuid4().hex}{ext}"
        dest = self.folder / name
        dest.write_bytes(content)
        return f"{self.url_prefix}/{name}"

    def delete(self, url: str) -> None:
        if not url or not url.startswith(self.url_prefix + "/"):
            return
        name = url.rsplit("/", 1)[-1]
        if not name or "/" in name or ".." in name:
            return
        path = self.folder / name
        try:
            path.unlink(missing_ok=True)
        except OSError as e:
            log.warning("Не удалось удалить %s: %s", path, e)


# ============================================================
# S3 / Cloudflare R2 / MinIO — готово к подключению
# ============================================================
class S3Storage(StorageBackend):
    def __init__(self, endpoint, bucket, access_key, secret_key, public_url):
        try:
            import boto3  # noqa: F401
        except ImportError:
            raise RuntimeError(
                "STORAGE_BACKEND=s3, но boto3 не установлен. "
                "Выполни: pip install boto3"
            )
        import boto3
        self.bucket = bucket
        self.public_url = public_url.rstrip("/")
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint,
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
        return f"{self.public_url}/{name}"

    def delete(self, url: str) -> None:
        if not url or not url.startswith(self.public_url + "/"):
            return
        name = url.rsplit("/", 1)[-1]
        if not name:
            return
        try:
            self.client.delete_object(Bucket=self.bucket, Key=name)
        except Exception as e:
            log.warning("Не удалось удалить %s из S3: %s", name, e)


# ============================================================
# Фабрика: выбираем бэкенд по .env
# ============================================================
def _make_backend() -> StorageBackend:
    if STORAGE_BACKEND == "s3":
        return S3Storage(
            endpoint=S3_ENDPOINT,
            bucket=S3_BUCKET,
            access_key=S3_ACCESS_KEY,
            secret_key=S3_SECRET_KEY,
            public_url=S3_PUBLIC_URL,
        )
    # по умолчанию — локальная папка
    return LocalStorage(
        folder=BASE_DIR / "static" / "uploads",
        url_prefix="/static/uploads",
    )


_backend = _make_backend()


# ============================================================
# Публичный API — этим пользуется весь остальной код
# ============================================================
def save_image(file) -> tuple[str | None, str | None]:
    """Сохраняет картинку из UploadFile.

    Возвращает (url, error):
      - (url, None)    — успех;
      - (None, None)   — файла не было или он пустой (не ошибка);
      - (None, "...")  — файл отклонён по конкретной причине.
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

    if (err := _verify_image(content)) is not None:
        return None, err

    url = _backend.save(content, ext)
    return url, None


def delete_image(url: str | None) -> None:
    """Удаляет картинку. Молча игнорирует всё, что не в нашем хранилище."""
    if url:
        _backend.delete(url)