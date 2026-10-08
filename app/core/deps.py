"""FastAPI-зависимости: CSRF, авторизация админа."""
import secrets

from fastapi import HTTPException, Request


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
    """Возвращает текущий CSRF-токен сессии, создавая его при необходимости."""
    token = request.session.get("csrf_token")
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