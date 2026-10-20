"""HTTP-мидлвари приложения."""
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import SESSION_HTTPS_ONLY


# CSP разрешает только нужные CDN. 'unsafe-inline' для script/style —
# вынужденная мера: Tailwind JIT вставляет inline-стили, а htmx — атрибуты.
# При vendoring Tailwind/FA/htmx — 'unsafe-inline' можно убрать.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' "
    "https://cdn.tailwindcss.com https://unpkg.com; "
    "style-src 'self' 'unsafe-inline' "
    "https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
    "font-src 'self' data: https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
    "img-src 'self' data: blob: https://images.unsplash.com; "
    "media-src 'self' blob:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self';"
)


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Отклоняет запросы, у которых Content-Length больше лимита.

    Рендерит ту же HTML-страницу ошибки, что и глобальный handler 413 —
    потому что этот middleware сидит СНАРУЖИ от ExceptionMiddleware,
    и его HTTPException не был бы пойман глобальными handlers.
    """

    def __init__(self, app, max_bytes: int):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            cl = request.headers.get("content-length")
            if cl and cl.isdigit() and int(cl) > self.max_bytes:
                return self._render_413(request)
        return await call_next(request)

    def _render_413(self, request):
        from app.core.rendering import admin_templates, site_templates

        is_admin = request.url.path.startswith("/admin")
        templates = admin_templates if is_admin else site_templates

        limit_mb = self.max_bytes // (1024 * 1024)

        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "error_code":    413,
                "error_title":   "Слишком большой запрос",
                "error_message": (
                    f"Файл превышает допустимый размер "
                    f"(лимит на весь запрос — {limit_mb} МБ). "
                    "Попробуйте загрузить файл поменьше."
                ),
                "error_icon":    "fa-weight-hanging",
            },
            status_code=413,
        )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Добавляет базовые security-заголовки к каждому ответу."""

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
        response.headers.setdefault(
            "Cross-Origin-Opener-Policy", "same-origin",
        )
        response.headers.setdefault("Content-Security-Policy", _CSP)
        if SESSION_HTTPS_ONLY:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response


class StaticCacheMiddleware(BaseHTTPMiddleware):
    """Долгий Cache-Control для статики."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)

        path = request.url.path

        if (
            path.startswith("/static/uploads/")
            or path.startswith("/static/site/")
        ):
            response.headers["Cache-Control"] = (
                "public, max-age=2592000, immutable"
            )
        elif path.startswith("/static/css/") or path.startswith("/static/js/"):
            response.headers["Cache-Control"] = (
                "public, max-age=86400"
            )

        return response


class AdminAuthGuardMiddleware(BaseHTTPMiddleware):
    """Единая защита /admin/*."""

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

        is_admin = (path == "/admin" or path.startswith("/admin/"))
        if not is_admin:
            return await call_next(request)

        if path == "/admin/login" or path.startswith("/admin/login/"):
            response = await call_next(request)
            return self._add_noindex(response)

        if not request.session.get("admin"):
            from starlette.responses import HTMLResponse
            response = HTMLResponse(
                content=self._NOT_FOUND_HTML,
                status_code=404,
            )
            return self._add_noindex(response)

        response = await call_next(request)
        return self._add_noindex(response)

    @staticmethod
    def _add_noindex(response):
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response