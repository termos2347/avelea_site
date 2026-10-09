"""Простой in-memory rate-limiter.

Используется для защиты /admin/login от перебора пароля.
Скользящее окно: не больше N попыток за M секунд на одного клиента.

Пока приложение работает в одном процессе — этого достаточно.
При переходе на несколько воркеров — заменить на Redis.
"""
import time
from collections import defaultdict, deque
from threading import Lock

_lock = Lock()
_attempts: dict[str, deque[float]] = defaultdict(deque)

DEFAULT_MAX = 5         # попыток
DEFAULT_WINDOW = 300    # за 5 минут


def _prune(q: deque[float], now: float, window: int) -> None:
    """Убирает из очереди метки старше окна."""
    while q and now - q[0] > window:
        q.popleft()


def is_blocked(
    key: str,
    max_attempts: int = DEFAULT_MAX,
    window: int = DEFAULT_WINDOW,
) -> bool:
    """True, если клиент исчерпал лимит."""
    now = time.monotonic()
    with _lock:
        q = _attempts[key]
        _prune(q, now, window)
        return len(q) >= max_attempts


def register_failure(key: str) -> None:
    """Отмечает одну неудачную попытку."""
    with _lock:
        _attempts[key].append(time.monotonic())


def reset(key: str) -> None:
    """Сбрасывает счётчик после успешного входа."""
    with _lock:
        _attempts.pop(key, None)


def reset_all() -> None:
    """Полная очистка — используется в тестах."""
    with _lock:
        _attempts.clear()


def client_key(request) -> str:
    """Идентификатор клиента для лимита.

    За localtunnel/прокси request.client.host — это IP туннеля,
    а не реальный. Поэтому читаем X-Forwarded-For, если он есть.
    Если приложение доступно напрямую без прокси — XFF можно
    подделать, но для защиты от перебора это некритично.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"