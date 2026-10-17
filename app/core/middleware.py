"""HTTP-мидлвари приложения."""
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import SESSION_HTTPS_ONLY


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
        response.headers.setdefault(
            "Cross-Origin-Opener-Policy", "same-origin",
        )
        if SESSION_HTTPS_ONLY:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response


class StaticCacheMiddleware(BaseHTTPMiddleware):
    """Долгий Cache-Control для статики.

    Три группы:

    1. /static/uploads/* — 30 дней, immutable.
       Файлы имеют уникальные имена (uuid), поэтому кеширование
       безопасно: один и тот же URL всегда отдаёт один и тот же
       файл. Браузер один раз скачает картинку и будет использовать
       её из локального кеша месяц.

    2. /static/css/*, /static/js/* — 1 день.
       CSS/JS могут обновляться при разработке, и мы хотим, чтобы
       браузер подтягивал свежие версии. 1 день — компромисс:
       заметная скорость загрузки при повторных визитах,
       но и обновления доходят в разумные сроки. Если понадобится
       мгновенное обновление — добавляй ?v=<hash> в шаблоны,
       и кэш будет сбрасываться при смене версии.

    3. Остальное (/static/favicon.ico и т.п.) — без Cache-Control,
       поведение по умолчанию от StaticFiles (ETag).

    /static/site/* — как uploads: uuid-имена, 30 дней immutable.
    """

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

    Дополнительно ко всем ответам из /admin/* ставим заголовок
    X-Robots-Tag: noindex, nofollow. Это защита от индексации
    на уровне HTTP — работает даже если робот не читал robots.txt
    (а мы там /admin явно не перечисляем — не подсказываем).
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