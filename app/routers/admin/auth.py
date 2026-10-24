"""Авторизация в админке: логин, логаут, редирект с /admin.

Логин двухшаговый, если настроен Telegram 2FA:
    1. POST /admin/login       — проверка пароля. При успехе генерится
                                 6-значный код, уходит в Telegram,
                                 а клиенту ставится opaque-token в сессию.
    2. POST /admin/login/2fa   — проверка кода. При успехе — session["admin"].

Если TELEGRAM_2FA_ENABLED=False (нет токена или admin_id в .env) —
шаг с кодом пропускается, логин работает как раньше.

CSRF-проверка на /admin/login и /admin/login/2fa делается вручную,
а не через Depends(check_csrf): при невалидном токене рендерим форму
с понятным сообщением, а не глобальную HTML-страницу 403.

Idle timeout реализован в AdminAuthGuardMiddleware (middleware.py):
если админ не делал запросов к /admin/* дольше SESSION_IDLE_TIMEOUT —
сессия инвалидируется. Здесь только ставим session["last_seen"] при
успешном логине.

Тип роутеров:
    - admin_login_submit — async def, потому что await _send_telegram_code
      (httpx.AsyncClient — реальный async I/O).
    - admin_login_2fa_submit — def, потому что _verify_code синхронный,
      без I/O. В threadpool не блокирует event loop.
    - Остальные — async def, потому что нет I/O (быстрые редиректы).
"""
import asyncio
import logging
import secrets
import threading
import time

import httpx
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.config import (
    ADMIN_PASSWORD,
    SESSION_IDLE_TIMEOUT,
    TELEGRAM_2FA_ENABLED,
    TELEGRAM_ADMIN_ID,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CODE_MAX_ATTEMPTS,
    TELEGRAM_CODE_TTL,
)
from app.core.security import (
    safe_str_compare,
    client_key,
    is_blocked,
    register_failure,
    reset,
)
from app.core.rendering import admin_templates

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin-auth"])


# ============================================================
# Хранилище ожидающих кодов (server-side)
# ============================================================
_pending_codes: dict[str, dict] = {}
_codes_lock = threading.RLock()


def _purge_expired(now: float | None = None) -> None:
    """Убирает протухшие коды. RLock берёт сам."""
    if now is None:
        now = time.time()
    with _codes_lock:
        expired = [t for t, v in _pending_codes.items() if v["expires"] < now]
        for t in expired:
            _pending_codes.pop(t, None)


async def purge_loop(interval: int = 60) -> None:
    """Фоново чистит протухшие коды 2FA."""
    try:
        while True:
            await asyncio.sleep(interval)
            _purge_expired()
    except asyncio.CancelledError:
        raise


def _new_code_entry() -> tuple[str, str]:
    """Создаёт запись о новом коде. Возвращает (token, code)."""
    token = secrets.token_urlsafe(16)
    code = f"{secrets.randbelow(1_000_000):06d}"
    with _codes_lock:
        _purge_expired()
        _pending_codes[token] = {
            "code": code,
            "expires": time.time() + TELEGRAM_CODE_TTL,
            "attempts": 0,
        }
    return token, code


def _verify_code(token: str, user_code: str) -> tuple[bool, str]:
    """Проверяет код. Возвращает (ok, error_message)."""
    if not token:
        return False, "Сессия истекла. Начните вход заново."

    with _codes_lock:
        _purge_expired()
        entry = _pending_codes.get(token)
        if entry is None:
            return False, "Код не найден или истёк. Начните вход заново."

        if entry["expires"] < time.time():
            _pending_codes.pop(token, None)
            return False, "Код истёк. Начните вход заново."

        entry["attempts"] += 1
        if entry["attempts"] > TELEGRAM_CODE_MAX_ATTEMPTS:
            _pending_codes.pop(token, None)
            return False, "Слишком много попыток. Начните вход заново."

        if not safe_str_compare(user_code, entry["code"]):
            left = TELEGRAM_CODE_MAX_ATTEMPTS - entry["attempts"] + 1
            return False, f"Неверный код. Осталось попыток: {left}"

        _pending_codes.pop(token, None)
    return True, ""


def _has_pending(token: str) -> bool:
    """True, если токен ещё жив в хранилище кодов."""
    if not token:
        return False
    with _codes_lock:
        _purge_expired()
        return token in _pending_codes


def _csrf_ok(request: Request, submitted: str) -> bool:
    """Проверка CSRF-токена, возвращает bool (не бросает исключение)."""
    session_token = request.session.get("csrf_token") or ""
    if not submitted or not session_token:
        return False
    return safe_str_compare(submitted, session_token)


def _session_valid(request: Request) -> bool:
    """True, если сессия валидна и не просрочена по idle timeout.

    Проверяется в admin_login_form: если админ с истёкшей сессией
    зайдёт на /admin/login, покажем форму логина вместо редиректа
    на /admin/products (где middleware выкинет 404 — цикл).
    """
    if not request.session.get("admin"):
        return False
    if SESSION_IDLE_TIMEOUT <= 0:
        return True
    last_seen = int(request.session.get("last_seen", 0))
    return (int(time.time()) - last_seen) <= SESSION_IDLE_TIMEOUT


def _login_success(request: Request) -> RedirectResponse:
    """Успешный логин: чистая сессия + admin + last_seen."""
    request.session.clear()
    request.session["admin"] = True
    request.session["last_seen"] = int(time.time())
    return RedirectResponse(url="/admin/products", status_code=303)


# ============================================================
# Отправка кода в Telegram
# ============================================================

async def _send_telegram_code(code: str) -> tuple[bool, str]:
    """Отправляет код в Telegram админу. Возвращает (ok, error_text)."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    text = (
        "🔐 Вход в админку Avelea\n\n"
        f"Код: {code}\n\n"
        f"Действует {TELEGRAM_CODE_TTL // 60} мин. "
        "Если это не вы — игнорируйте и смените пароль."
    )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json={
                "chat_id": TELEGRAM_ADMIN_ID,
                "text": text,
                "disable_notification": False,
            })
    except Exception as e:
        log.exception("Ошибка отправки в Telegram: %s", e)
        return False, "Не удалось отправить код в Telegram. Попробуйте позже."

    if r.status_code != 200:
        log.error("Telegram вернул %s: %s", r.status_code, r.text[:200])
        return False, "Telegram отклонил запрос. Проверьте настройки бота."

    return True, ""


# ============================================================
# GET /admin/login — форма пароля
# ============================================================

@router.get("/login", response_class=HTMLResponse)
async def admin_login_form(request: Request):
    if _session_valid(request):
        return RedirectResponse(url="/admin/products", status_code=303)

    # Если admin-флаг есть, но сессия просрочена по idle timeout —
    # чистим, чтобы middleware не выкинул 404 после редиректа.
    if request.session.get("admin"):
        request.session.clear()

    pending = request.session.get("pending_2fa_token")
    if pending and not _has_pending(pending):
        # Код истёк или вычищен purge_loop'ом — забываем токен,
        # чтобы не крутить пользователя по циклу
        # /admin/login → /admin/login/2fa → «код истёк» → /admin/login.
        request.session.pop("pending_2fa_token", None)
        pending = None

    if TELEGRAM_2FA_ENABLED and pending:
        return RedirectResponse(url="/admin/login/2fa", status_code=303)

    return admin_templates.TemplateResponse(request, "login.html", {
        "step": "password",
        "error": None,
    })


# ============================================================
# POST /admin/login — проверка пароля
# ============================================================

@router.post("/login")
async def admin_login_submit(
    request: Request,
    password: str = Form(...),
    csrf_token: str = Form(""),
):
    if not _csrf_ok(request, csrf_token):
        return admin_templates.TemplateResponse(
            request, "login.html",
            {
                "step": "password",
                "error": "Сессия истекла или cookie не переданы. "
                         "Обновите страницу и попробуйте снова.",
            },
            status_code=403,
        )

    key = client_key(request)

    if is_blocked(key):
        return admin_templates.TemplateResponse(
            request, "login.html",
            {
                "step": "password",
                "error": "Слишком много попыток входа. Попробуйте через 5 минут.",
            },
            status_code=429,
        )

    if not safe_str_compare(password, ADMIN_PASSWORD):
        register_failure(key)
        return admin_templates.TemplateResponse(
            request, "login.html",
            {"step": "password", "error": "Неверный пароль"},
            status_code=401,
        )

    reset(key)

    if not TELEGRAM_2FA_ENABLED:
        return _login_success(request)

    # Отдельный лимит на отправку 2FA-кодов (пароль уже верный).
    # 5 запросов за 5 минут: 3 слишком мало, если админ
    # перенастраивает магазин и перезаходит подряд.
    code_key = f"login-code:{key}"
    if is_blocked(code_key, max_attempts=5, window=300):
        return admin_templates.TemplateResponse(
            request, "login.html",
            {
                "step": "password",
                "error": "Слишком много запросов кода. Попробуйте через 5 минут.",
            },
            status_code=429,
        )
    register_failure(code_key, window=300)

    token, code = _new_code_entry()
    request.session["pending_2fa_token"] = token

    ok, err = await _send_telegram_code(code)
    if not ok:
        with _codes_lock:
            _pending_codes.pop(token, None)
        request.session.pop("pending_2fa_token", None)
        return admin_templates.TemplateResponse(
            request, "login.html",
            {"step": "password", "error": err},
            status_code=503,
        )

    return RedirectResponse(url="/admin/login/2fa", status_code=303)


# ============================================================
# GET /admin/login/2fa — форма ввода кода
# ============================================================

@router.get("/login/2fa", response_class=HTMLResponse)
async def admin_login_2fa_form(request: Request):
    if _session_valid(request):
        return RedirectResponse(url="/admin/products", status_code=303)

    token = request.session.get("pending_2fa_token")
    if not token or not _has_pending(token):
        if token:
            request.session.pop("pending_2fa_token", None)
        return RedirectResponse(url="/admin/login", status_code=303)

    return admin_templates.TemplateResponse(request, "login.html", {
        "step": "code",
        "error": None,
        "code_ttl_minutes": TELEGRAM_CODE_TTL // 60,
    })


# ============================================================
# POST /admin/login/2fa — проверка кода
# ============================================================

@router.post("/login/2fa")
def admin_login_2fa_submit(
    request: Request,
    code: str = Form(...),
    csrf_token: str = Form(""),
):
    if _session_valid(request):
        return RedirectResponse(url="/admin/products", status_code=303)

    token = request.session.get("pending_2fa_token")
    if not token:
        return RedirectResponse(url="/admin/login", status_code=303)

    if not _csrf_ok(request, csrf_token):
        return admin_templates.TemplateResponse(
            request, "login.html",
            {
                "step": "code",
                "error": "Сессия истекла или cookie не переданы. "
                         "Обновите страницу и начните вход заново.",
                "code_ttl_minutes": TELEGRAM_CODE_TTL // 60,
            },
            status_code=403,
        )

    ok, err = _verify_code(token, code.strip())
    if not ok:
        if not _has_pending(token):
            request.session.pop("pending_2fa_token", None)
            return RedirectResponse(url="/admin/login", status_code=303)

        return admin_templates.TemplateResponse(
            request, "login.html",
            {
                "step": "code",
                "error": err,
                "code_ttl_minutes": TELEGRAM_CODE_TTL // 60,
            },
            status_code=401,
        )

    # Успех — сбрасываем счётчик запросов кода. Без этого
    # 5 успешных входов за 5 минут залипали бы в 429 на 6-й
    # (register_failure вызывается до отправки, а reset — нет).
    reset(f"login-code:{client_key(request)}")

    return _login_success(request)


# ============================================================
# Logout / редиректы
# ============================================================

@router.post("/logout")
async def admin_logout(request: Request):
    """Выход из админки.

    POST, не GET — чтобы `<img src="/admin/logout">` с чужого сайта
    не мог выкинуть админа.

    CSRF осознанно НЕ проверяется: выкидывание из сессии — не
    деструктивная операция (не удаляет данные, не меняет состояние
    на сервере). CSRF-атака на logout = максимум DoS, не компрометация.
    """
    token = request.session.get("pending_2fa_token")
    if token:
        with _codes_lock:
            _pending_codes.pop(token, None)
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=303)


@router.get("", response_class=HTMLResponse)
async def admin_root(request: Request):
    return RedirectResponse(url="/admin/products", status_code=303)