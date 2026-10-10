"""Авторизация в админке: логин, логаут, редирект с /admin.

Логин двухшаговый, если настроен Telegram 2FA:
    1. POST /admin/login       — проверка пароля. При успехе генерится
                                 6-значный код, уходит в Telegram,
                                 а клиенту ставится opaque-token в сессию.
    2. POST /admin/login/2fa   — проверка кода. При успехе — session["admin"].

Если TELEGRAM_2FA_ENABLED=False (нет токена или admin_id в .env) —
шаг с кодом пропускается, логин работает как раньше.
"""
import logging
import secrets
import threading
import time

import httpx
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.config import (
    ADMIN_PASSWORD,
    TELEGRAM_2FA_ENABLED,
    TELEGRAM_ADMIN_ID,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CODE_MAX_ATTEMPTS,
    TELEGRAM_CODE_TTL,
)
from app.core.deps import check_csrf, safe_str_compare
from app.core.ratelimit import (
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
# ------------------------------------------------------------
# Клиенту в сессию кладём только opaque-token. Сам код живёт
# здесь — иначе его можно было бы выковырять из cookie
# (SessionMiddleware подписывает, но НЕ шифрует).
#
# Формат: token -> {"code": "123456", "expires": ts, "attempts": 0}
# ============================================================
_pending_codes: dict[str, dict] = {}
_codes_lock = threading.Lock()


def _purge_expired(now: float | None = None) -> None:
    """Убирает протухшие коды. Вызывается при каждом обращении."""
    if now is None:
        now = time.time()
    expired = [t for t, v in _pending_codes.items() if v["expires"] < now]
    for t in expired:
        _pending_codes.pop(t, None)


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
    """Проверяет код. Возвращает (ok, error_message).

    Может удалить запись при превышении попыток или истечении TTL.
    """
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

        # Успех — забираем запись, чтобы код нельзя было использовать дважды.
        _pending_codes.pop(token, None)
    return True, ""


def _has_pending(token: str) -> bool:
    """True, если токен ещё жив в хранилище кодов."""
    if not token:
        return False
    with _codes_lock:
        _purge_expired()
        return token in _pending_codes
    
# ============================================================
# Отправка кода в Telegram
# ============================================================

async def _send_telegram_code(code: str) -> tuple[bool, str]:
    """Отправляет код в Telegram админу. Возвращает (ok, error_text).

    Таймаут 10 секунд — если Telegram не отвечает, лучше сказать
    пользователю «не получилось», чем держать воркер.
    """
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
    if request.session.get("admin"):
        return RedirectResponse(url="/admin/products", status_code=303)

    # Если уже висит pending-код — сразу на второй шаг.
    if TELEGRAM_2FA_ENABLED and request.session.get("pending_2fa_token"):
        return RedirectResponse(url="/admin/login/2fa", status_code=303)

    return admin_templates.TemplateResponse(request, "login.html", {
        "step": "password",
        "error": None,
    })


# ============================================================
# POST /admin/login — проверка пароля
# ============================================================

@router.post("/login", dependencies=[Depends(check_csrf)])
async def admin_login_submit(request: Request, password: str = Form(...)):
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

    # Пароль верный. Сбрасываем счётчик неудач.
    reset(key)

    # 2FA выключен → пускаем сразу (dev-режим, тесты).
    if not TELEGRAM_2FA_ENABLED:
        request.session["admin"] = True
        request.session.pop("csrf_token", None)
        request.session.pop("pending_2fa_token", None)
        return RedirectResponse(url="/admin/products", status_code=303)

    # Отдельный rate-limit на отправку кодов: даже зная пароль,
    # нельзя спамить админу в Telegram.
    code_key = f"login-code:{key}"
    if is_blocked(code_key, max_attempts=3, window=300):
        return admin_templates.TemplateResponse(
            request, "login.html",
            {
                "step": "password",
                "error": "Слишком много запросов кода. Попробуйте через 5 минут.",
            },
            status_code=429,
        )
    register_failure(code_key)

    # Генерируем код, кладём в server-side хранилище,
    # клиенту отдаём только opaque-token.
    token, code = _new_code_entry()
    request.session["pending_2fa_token"] = token

    ok, err = await _send_telegram_code(code)
    if not ok:
        # Не смогли отправить — сбрасываем, чтобы не висел мёртвый код.
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
    if request.session.get("admin"):
        return RedirectResponse(url="/admin/products", status_code=303)

    token = request.session.get("pending_2fa_token")
    if not token:
        # Нет pending-кода — начинаем заново.
        return RedirectResponse(url="/admin/login", status_code=303)

    return admin_templates.TemplateResponse(request, "login.html", {
        "step": "code",
        "error": None,
        "code_ttl_minutes": TELEGRAM_CODE_TTL // 60,
    })


# ============================================================
# POST /admin/login/2fa — проверка кода
# ============================================================

@router.post("/login/2fa", dependencies=[Depends(check_csrf)])
async def admin_login_2fa_submit(request: Request, code: str = Form(...)):
    if request.session.get("admin"):
        return RedirectResponse(url="/admin/products", status_code=303)

    token = request.session.get("pending_2fa_token")
    if not token:
        return RedirectResponse(url="/admin/login", status_code=303)

    ok, err = _verify_code(token, code.strip())
    if not ok:
        # Запись могла «сгореть»: код истёк или попытки закончились.
        # В этом случае токен уже удалён из _pending_codes — надо
        # вычистить и сессию и вернуть пользователя к шагу пароля.
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

    # Успех.
    request.session["admin"] = True
    request.session.pop("pending_2fa_token", None)
    request.session.pop("csrf_token", None)
    return RedirectResponse(url="/admin/products", status_code=303)

# ============================================================
# Logout / редиректы
# ============================================================

@router.get("/logout")
async def admin_logout(request: Request):
    # Убираем и pending, если был.
    token = request.session.get("pending_2fa_token")
    if token:
        with _codes_lock:
            _pending_codes.pop(token, None)
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=303)


@router.get("", response_class=HTMLResponse)
async def admin_root(request: Request):
    return RedirectResponse(url="/admin/products", status_code=303)