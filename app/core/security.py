"""FastAPI-зависимости безопасности: CSRF, авторизация админа, rate-limit.

Объединяет бывшие deps.py и ratelimit.py — оба про защиту роутеров.
"""
import secrets
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, Request

from app.core.config import TRUSTED_PROXIES


# ============================================================
# CSRF + авторизация админа
# ============================================================

class NotAuthenticated(Exception):
    """Сессия не содержит admin-флага.

    Обработчик регистрируется в app/main.py и редиректит на /admin/login.
    """


def safe_str_compare(a: str, b: str) -> bool:
    """Сравнение строк, устойчивое к timing-атакам."""
    try:
        return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
    except (TypeError, ValueError):
        return False


def get_csrf_token(request: Request) -> str:
    """Возвращает текущий CSRF-токен сессии, создавая его при необходимости.

    Возвращает пустую строку, если SessionMiddleware нет в цепочке
    (например, 413 от BodySizeLimitMiddleware срабатывает до Session).
    Пустой токен = CSRF-проверка потом отклонит форму, но страница
    отрендерится без 500.
    """
    try:
        token = request.session.get("csrf_token")
    except (AttributeError, AssertionError):
        return ""

    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


async def check_csrf(request: Request) -> None:
    """Проверяет csrf_token в форме против значения в сессии."""
    form = await request.form()
    token = form.get("csrf_token")
    session_token = request.session.get("csrf_token")

    if not token or not session_token:
        raise HTTPException(status_code=403, detail="CSRF token invalid")

    if not safe_str_compare(str(token), str(session_token)):
        raise HTTPException(status_code=403, detail="CSRF token invalid")


async def require_admin(request: Request) -> bool:
    """Защита админских роутов.

    Для write-методов дополнительно проверяет CSRF.
    """
    if not request.session.get("admin"):
        raise NotAuthenticated()
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        await check_csrf(request)
    return True


# ============================================================
# Rate-limit (in-memory)
# ============================================================
# Пока приложение работает в одном процессе — этого достаточно.
# При переходе на несколько воркеров — заменить на Redis.
# ============================================================

_lock = Lock()
_attempts: dict[str, deque[float]] = defaultdict(deque)

# Верхняя граница ключей. Защита от memory-DoS: атакующий с 1M
# уникальных XFF иначе раздует dict на сотни MB.
_MAX_TRACKED_KEYS = 10_000
_last_purge = 0.0

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
    """True, если клиент исчерпал лимит.

    Не создаёт запись в _attempts для незнакомых ключей — иначе
    атакующий уникальными XFF раздувает dict.
    """
    now = time.monotonic()
    with _lock:
        q = _attempts.get(key)
        if q is None:
            return False
        _prune(q, now, window)
        return len(q) >= max_attempts


def register_failure(key: str) -> None:
    """Отмечает одну неудачную попытку.

    Не даёт dict расти безгранично: при достижении лимита ключей
    новые не отслеживаются (fail-open, чтобы не жечь RAM).
    Периодически чистит пустые deque (раз в минуту).
    """
    global _last_purge
    now = time.monotonic()
    with _lock:
        if key not in _attempts and len(_attempts) >= _MAX_TRACKED_KEYS:
            return
        _attempts[key].append(now)

        if now - _last_purge > 60:
            _last_purge = now
            for k in list(_attempts.keys()):
                q = _attempts[k]
                _prune(q, now, DEFAULT_WINDOW)
                if not q:
                    del _attempts[k]


def reset(key: str) -> None:
    """Сбрасывает счётчик после успешного входа."""
    with _lock:
        _attempts.pop(key, None)


def reset_all() -> None:
    """Полная очистка — используется в тестах."""
    global _last_purge
    with _lock:
        _attempts.clear()
        _last_purge = 0.0


def client_key(request) -> str:
    """Идентификатор клиента для лимита.

    X-Forwarded-For учитывается ТОЛЬКО от доверенных прокси
    (TRUSTED_PROXIES). Иначе заголовок подделывается клиентом,
    и каждый запрос получает свой bucket — brute-force не блокируется.

    Парсим справа налево: правый элемент дописал ближайший доверенный
    прокси (реальный клиент, если прокси один — типичный nginx с
    `$proxy_add_x_forwarded_for`). Левый край — клиентский мусор.
    """
    direct = request.client.host if request.client else "unknown"

    # Пришло не от прокси → XFF подделывается, игнорируем.
    if direct not in TRUSTED_PROXIES:
        return direct

    xff = request.headers.get("x-forwarded-for", "")
    if not xff:
        return direct

    parts = [p.strip() for p in xff.split(",") if p.strip()]
    while parts and parts[-1] in TRUSTED_PROXIES:
        parts.pop()

    return parts[-1] if parts else direct