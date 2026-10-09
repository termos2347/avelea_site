"""HTTP-мидлвари приложения."""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse


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
        return response