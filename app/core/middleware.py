"""HTTP-мидлвари приложения."""
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import SESSION_HTTPS_ONLY, SESSION_IDLE_TIMEOUT
from app.utils.helpers import is_ajax


# CSP разрешает только нужные CDN.
# script-src: без 'unsafe-inline' — все скрипты вынесены в /static/js/.
# style-src:  'unsafe-inline' вынужденно — Tailwind JIT вставляет
#             inline-стили динамически. При vendoring Tailwind — убрать.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' "
    "https://cdn.tailwindcss.com https://unpkg.com; "
    "style-src 'self' 'unsafe-inline' "
    "https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
    "font-src 'self' data: https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
    "img-src 'self' data: blob:; "
    "media-src 'self' blob:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self';"
)


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Отклоняет запросы, у которых Content-Length больше лимита."""

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
        limit_mb = self.max_bytes // (1024 * 1024)

        if is_ajax(request):
            return JSONResponse(
                {
                    "ok": False,
                    "error": (
                        f"Файл слишком большой "
                        f"(лимит на весь запрос — {limit_mb} МБ)."
                    ),
                },
                status_code=413,
            )

        from app.core.rendering import admin_templates, site_templates

        is_admin = request.url.path.startswith("/admin")
        templates = admin_templates if is_admin else site_templates

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
    """Единая защита /admin/*.

    Помимо проверки session["admin"], реализует idle timeout:
    если админ не делал ни одного запроса к /admin/* дольше
    SESSION_IDLE_TIMEOUT секунд — сессия инвалидируется.

    /admin/login и /admin/login/2fa пропускаются без проверки —
    иначе после истечения idle нельзя было бы залогиниться заново.
    """

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
            return self._add_noindex(self._render_404())

        # Idle timeout: проверяем, сколько прошло с последнего действия.
        # SESSION_IDLE_TIMEOUT <= 0 — отключено.
        if SESSION_IDLE_TIMEOUT > 0:
            now = int(time.time())
            last_seen = int(request.session.get("last_seen", now))
            if now - last_seen > SESSION_IDLE_TIMEOUT:
                request.session.clear()
                return self._add_noindex(self._render_404())
            request.session["last_seen"] = now

        response = await call_next(request)
        return self._add_noindex(response)

    def _render_404(self):
        from starlette.responses import HTMLResponse
        return HTMLResponse(
            content=self._NOT_FOUND_HTML,
            status_code=404,
        )

    @staticmethod
    def _add_noindex(response):
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response