"""HTTP-мидлвари приложения."""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import HTMLResponse, PlainTextResponse

from app.core.config import SESSION_HTTPS_ONLY


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Отклоняет запросы, у которых Content-Length больше лимита."""

    def __init__(self, app, max_bytes: int):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            cl = request.headers.get("content-length")
            if cl and cl.isdigit() and int(cl) > self.max_bytes:
                return PlainTextResponse(
                    f"Файл слишком большой "
                    f"(лимит {self.max_bytes // (1024 * 1024)} МБ)",
                    status_code=413,
                )
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Добавляет базовые security-заголовки к каждому ответу.

    CSP не ставим — Tailwind и Font Awesome подключены через CDN
    с inline-стилями, дефолтная политика их сломает.

    HSTS включается автоматически, если приложение крутится за HTTPS
    (сигнал — SESSION_HTTPS_ONLY=True).
    """

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin",
        )
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=()",
        )
        if SESSION_HTTPS_ONLY:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response


class AdminAuthGuardMiddleware(BaseHTTPMiddleware):
    """Единая защита /admin/*.

    Зачем нужен отдельный middleware, если уже есть require_admin
    на роутерах: этот guard срабатывает РАНЬШЕ роутера. Значит,
    он ловит и те URL, под которые вообще нет роутов
    (/admin/what-is-this). Без него такие запросы попадали в
    глобальный 404-обработчик, а тот видел `/admin/` в пути и
    отрисовывал админский шаблон ошибки — палево.

    Логика:
      - /admin/login*               → пропускаем (иначе как войти);
      - /admin/* без активной сессии → отдаём обычную 404 как сайт,
                                        без единого намёка на админку;
      - /admin/* с сессией           → пропускаем, дальше рулит
                                        require_admin на роутерах.
    """

    # Плейн-HTML вместо шаблона: рендер Jinja из middleware
    # требует передачи Request, а это лишний риск. Страница — 15 строк.
    _NOT_FOUND_HTML = (
        "<!DOCTYPE html>"
        "<html lang='ru'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>404 — не найдено</title></head>"
        "<body style=\"font-family:-apple-system,BlinkMacSystemFont,"
        "'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;"
        "padding:3rem 1.5rem;max-width:36rem;margin:0 auto;"
        "color:#111827;line-height:1.5\">"
        "<div style='font-size:3rem;font-weight:600;"
        "letter-spacing:-0.03em'>404</div>"
        "<p style='color:#6b7280;font-size:1rem;margin:0.5rem 0 1.5rem'>"
        "Такой страницы нет.</p>"
        "<a href='/' style='color:#111827;text-decoration:underline;"
        "text-underline-offset:3px'>На главную</a>"
        "</body></html>"
    )

    async def dispatch(self, request, call_next):
        path = request.url.path

        # Открыто: /admin/login и всё под ним
        if path == "/admin/login" or path.startswith("/admin/login/"):
            return await call_next(request)

        # Закрыто: любой другой /admin или /admin/*
        if path == "/admin" or path.startswith("/admin/"):
            if not request.session.get("admin"):
                return HTMLResponse(
                    content=self._NOT_FOUND_HTML,
                    status_code=404,
                )

        return await call_next(request)