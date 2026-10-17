"""Абстракция хранилища медиафайлов (картинки + видео).

Все картинки автоматически конвертируются в WebP (кроме GIF —
у них сохраняется анимация). Это даёт 30-70% экономии места
при том же визуальном качестве. Видео сохраняется как есть.

В БД лежит только имя файла ("abc123.webp" или "video.mp4").
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


# Качество WebP при сохранении. 85 — визуально неотличимо от оригинала
# для фото, но даёт 30-50% экономии. Можно поднять до 90, если захочешь
# идеальное качество ценой размера файла.
WEBP_QUALITY = 85
# method=6 — максимальное сжатие (медленнее на 50-100 мс, но файл меньше).
WEBP_METHOD = 6


# ============================================================
# Определение типа файла по magic bytes
# ============================================================
_MAGIC = (
    (b"\xff\xd8\xff",          ".jpg"),
    (b"\x89PNG\r\n\x1a\n",     ".png"),
    (b"GIF87a",                ".gif"),
    (b"GIF89a",                ".gif"),
    (b"\x1a\x45\xdf\xa3",      ".webm"),
)

# Только те форматы, для которых есть magic-bytes в _MAGIC.
# .ogv (Ogg Video) здесь НЕ упомянут: у него нет magic в _MAGIC,
# поэтому _sniff_ext его не пропустит — и держать его в списке
# «разрешённых» означает врать пользователю в сообщении об ошибке.
_VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v"}

_ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "GIF", "WEBP"}
_READ_CHUNK = 64 * 1024

_RESAMPLE = (
    Image.Resampling.LANCZOS
    if hasattr(Image, "Resampling")
    else Image.LANCZOS
)


def _sniff_ext(head: bytes) -> tuple[str | None, bool]:
    """Определяет расширение и является ли файл видео.

    Возвращает (ext, is_video).
    """
    for magic, ext in _MAGIC:
        if head.startswith(magic):
            return ext, ext in _VIDEO_EXTS

    # WEBP: RIFF....WEBP
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp", False

    # MP4/MOV: байты 4-8 == 'ftyp'
    if len(head) >= 12 and head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand == b"qt  ":
            return ".mov", True
        return ".mp4", True

    return None, False


def is_video(filename: str | None) -> bool:
    """True, если имя файла соответствует видео-формату."""
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
    """Обрабатывает картинку.

    Возвращает (new_content, new_ext, error):
      - GIF: сохраняется как есть (сохраняет анимацию) → (bytes, ".gif", None)
      - WebP и не превышает MAX_IMAGE_DIMENSION: как есть → (bytes, ".webp", None)
      - Всё остальное: ресайз (если нужен) + конвертация в WebP.
      - Ошибка: (None, None, "текст")
    """
    # Первый проход — валидация формата и целостности.
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
        return None, None, (
            "Файл повреждён или не является изображением — файл не сохранён."
        )

    # GIF не трогаем — ресайз и конвертация сломают анимацию.
    with Image.open(io.BytesIO(content)) as img:
        if img.format == "GIF":
            return content, ".gif", None

        # Уже WebP и в пределах лимита — не пере-сжимаем повторно.
        if img.format == "WEBP" and (
            MAX_IMAGE_DIMENSION <= 0 or max(img.size) <= MAX_IMAGE_DIMENSION
        ):
            return content, ".webp", None

    # Основная обработка: ресайз + WebP.
    try:
        with Image.open(io.BytesIO(content)) as img:
            if MAX_IMAGE_DIMENSION > 0 and max(img.size) > MAX_IMAGE_DIMENSION:
                img.thumbnail(
                    (MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION),
                    _RESAMPLE,
                )

            # WebP не любит некоторые режимы Pillow (P, LA, I, F).
            # Приводим к RGB или RGBA — от этого зависит прозрачность.
            if img.mode not in ("RGB", "RGBA"):
                if img.mode in ("P", "LA") or "transparency" in img.info:
                    img = img.convert("RGBA")
                else:
                    img = img.convert("RGB")

            buf = io.BytesIO()
            img.save(
                buf,
                format="WEBP",
                quality=WEBP_QUALITY,
                method=WEBP_METHOD,
            )
            return buf.getvalue(), ".webp", None
    except (OSError, ValueError) as e:
        log.warning("WebP-конвертация не удалась: %s", e)
        return None, None, (
            "Не удалось обработать изображение — попробуйте другой файл."
        )


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
# Публичный API
# ============================================================
def save_media(file) -> tuple[str | None, str | None]:
    """Сохраняет картинку или видео.

    Картинки автоматически конвертируются в WebP (кроме GIF).
    Возвращает (filename, error):
      - (filename, None) — успех;
      - (None, None)     — файла не было / пустой (не ошибка);
      - (None, "...")    — отклонён с причиной.

    Поддерживаемые форматы (определяются по magic-bytes, не по
    расширению):

    Картинки: jpg, png, gif, webp.
    Видео:    mp4, webm, mov (включая m4v — тот же контейнер).
    """
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

    # Картинка — оптимизация + WebP.
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


# Обратная совместимость со старым кодом.
save_image = save_media
delete_image = delete_media