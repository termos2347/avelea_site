"""Точка сборки приложения."""
import asyncio
import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from xml.sax.saxutils import escape

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import (
    AUTO_MIGRATE,
    BASE_DIR,
    MAX_UPLOAD_BYTES,
    MAX_VIDEO_UPLOAD_BYTES,
    SECRET_KEY,
    SESSION_HTTPS_ONLY,
    SESSION_MAX_AGE,
    SESSION_SAME_SITE,
    SITE_PUBLIC,
    TELEGRAM_2FA_ENABLED,
    UVICORN_WORKERS,
)
from app.core.database import SessionLocal
from app.core.security import NotAuthenticated
from app.core.middleware import (
    AdminAuthGuardMiddleware,
    BodySizeLimitMiddleware,
    SecurityHeadersMiddleware,
    StaticCacheMiddleware,
)
from app.core.rendering import admin_templates, site_templates
from app.data import cache
from app.data.seed import seed_database
from app.routers import site
from app.routers.admin import auth, catalog, products, site_content

(BASE_DIR / "instance").mkdir(exist_ok=True)
(BASE_DIR / "static" / "uploads").mkdir(parents=True, exist_ok=True)
(BASE_DIR / "static" / "site").mkdir(parents=True, exist_ok=True)

_ALEMBIC_INI = BASE_DIR / "alembic.ini"


_LOG_DIR = BASE_DIR / "instance" / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

_formatter = logging.Formatter(
    fmt="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_console = logging.StreamHandler()
_console.setFormatter(_formatter)

_file = RotatingFileHandler(
    _LOG_DIR / "avelea.log",
    maxBytes=5 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8",
)
_file.setFormatter(_formatter)

logging.basicConfig(level=logging.INFO, handlers=[_console, _file])

for _name in ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi"):
    _uv = logging.getLogger(_name)
    _uv.handlers.clear()
    _uv.propagate = True

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

log = logging.getLogger("avelea")


def _ensure_migrations_current(alembic_cfg: Config) -> None:
    """Проверяет, что БД накачена до head. Иначе — отказ стартовать."""
    from app.core.database import engine as app_engine

    script = ScriptDirectory.from_config(alembic_cfg)
    head = script.get_current_head()

    with app_engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()

    if current != head:
        log.error(
            "Миграции не применены: current=%s, head=%s. "
            "Выполните `alembic upgrade head` и перезапустите приложение.",
            current, head,
        )
        raise SystemExit(1)

    log.info("Миграции актуальны: %s", current)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if UVICORN_WORKERS > 1:
        log.warning(
            "⚠️  UVICORN_WORKERS=%d. In-memory кэш и rate-limiter работают "
            "только в одном процессе. Для продакшена — один воркер или Redis.",
            UVICORN_WORKERS,
        )

    alembic_cfg = Config(str(_ALEMBIC_INI))

    if AUTO_MIGRATE:
        log.info("Запуск: миграции Alembic (AUTO_MIGRATE=true)")
        command.upgrade(alembic_cfg, "head")
    else:
        log.info("AUTO_MIGRATE=false — проверяю актуальность миграций")
        _ensure_migrations_current(alembic_cfg)

    db = SessionLocal()
    try:
        seed_database(db)
    finally:
        db.close()

    cache.reload_all()

    try:
        from app.services.storage import cleanup_orphans
        removed = cleanup_orphans(min_age_minutes=60, dry_run=False)
        total = len(removed["site"]) + len(removed["uploads"])
        if total:
            log.info(
                "Очистка orphan: удалено site=%d, uploads=%d",
                len(removed["site"]), len(removed["uploads"]),
            )
        else:
            log.info("Очистка orphan: чисто")
    except Exception as exc:
        log.exception("cleanup_orphans упал (продолжаем): %s", exc)

    purge_task: asyncio.Task | None = None
    if TELEGRAM_2FA_ENABLED:
        purge_task = asyncio.create_task(auth.purge_loop())
        log.info("Фоновая чистка 2FA-кодов запущена")

    log.info("Кэш прогрет. Приложение готово")

    try:
        yield
    finally:
        if purge_task is not None:
            purge_task.cancel()
            try:
                await purge_task
            except asyncio.CancelledError:
                pass
            log.info("Фоновая чистка 2FA-кодов остановлена")

        log.info("Остановка")


app = FastAPI(title="Avelea Shop", lifespan=lifespan)

app.add_middleware(GZipMiddleware, minimum_size=800)
app.add_middleware(AdminAuthGuardMiddleware)

app.add_middleware(
    BodySizeLimitMiddleware,
    max_bytes=4 * max(MAX_UPLOAD_BYTES, MAX_VIDEO_UPLOAD_BYTES) + 1024 * 1024,
)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    https_only=SESSION_HTTPS_ONLY,
    same_site=SESSION_SAME_SITE,
    max_age=SESSION_MAX_AGE,
)

app.add_middleware(StaticCacheMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)


@app.get("/healthz", include_in_schema=False)
async def healthz():
    from sqlalchemy import text as sa_text

    db = SessionLocal()
    try:
        db.execute(sa_text("SELECT 1"))
    except Exception as exc:
        log.error("healthz: db check failed: %s", exc)
        return JSONResponse(
            {"ok": False, "error": "db_unavailable"},
            status_code=503,
        )
    finally:
        db.close()

    return {"ok": True}


@app.get("/robots.txt", include_in_schema=False, response_class=PlainTextResponse)
async def robots_txt(request: Request):
    if not SITE_PUBLIC:
        # Staging/разработка: закрываем от поисковиков.
        return PlainTextResponse(
            "User-agent: *\n"
            "Disallow: /\n"
        )

    base = str(request.base_url).rstrip("/")
    return PlainTextResponse(
        "User-agent: *\n"
        "Allow: /\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap_xml(request: Request):
    if not SITE_PUBLIC:
        # На staging sitemap не отдаём — чтобы не подсказывать поисковикам.
        return Response(content="", media_type="application/xml", status_code=404)

    base = str(request.base_url).rstrip("/")

    urls = [
        f"{base}/",
        f"{base}/catalog",
        f"{base}/brands",
        f"{base}/about",
    ]
    for p in cache.get_products():
        if not p.is_active:
            continue
        urls.append(f"{base}/product/{p.slug or p.id}")

    body = '<?xml version="1.0" encoding="UTF-8"?>\n'
    body += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for u in urls:
        body += f"  <url><loc>{escape(u)}</loc></url>\n"
    body += "</urlset>\n"

    return Response(content=body, media_type="application/xml")


_ERROR_PAGES: dict[int, dict] = {
    400: {
        "title": "Некорректный запрос",
        "message": "Запрос не удалось обработать. Проверьте данные и попробуйте ещё раз.",
        "icon":  "fa-triangle-exclamation",
    },
    403: {
        "title": "Доступ запрещён",
        "message": "У вас нет прав на это действие.",
        "icon":  "fa-lock",
    },
    404: {
        "title": "Страница не найдена",
        "message": "Такой страницы на сайте нет. Возможно, ссылка устарела или в ней опечатка.",
        "icon":  "fa-magnifying-glass",
    },
    405: {
        "title": "Метод не поддерживается",
        "message": "Этот запрос нельзя выполнить таким способом.",
        "icon":  "fa-ban",
    },
    413: {
        "title": "Слишком большой запрос",
        "message": "Загружаемый файл превышает допустимый размер.",
        "icon":  "fa-weight-hanging",
    },
    429: {
        "title": "Слишком много запросов",
        "message": "Попробуйте ещё раз через минуту.",
        "icon":  "fa-hourglass-half",
    },
    500: {
        "title": "Что-то пошло не так",
        "message": "Мы уже разбираемся. Обновите страницу через минуту или вернитесь на главную.",
        "icon":  "fa-triangle-exclamation",
    },
}


_JSON_ERROR_MESSAGES: dict[int, str] = {
    400: "Некорректный запрос. Проверьте данные.",
    403: "Сессия истекла или доступ запрещён. Обновите страницу и попробуйте снова.",
    404: "Не найдено.",
    405: "Метод не поддерживается.",
    413: "Слишком большой запрос.",
    429: "Слишком много запросов. Попробуйте через минуту.",
    500: "Внутренняя ошибка. Попробуйте ещё раз.",
}


def _is_ajax(request: Request) -> bool:
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _json_error_message(status_code: int) -> str:
    return _JSON_ERROR_MESSAGES.get(status_code, "Ошибка.")


def _pick_error_preset(status_code: int, path: str) -> dict:
    if status_code == 404:
        if path.startswith("/product/"):
            return {
                "title":   "Товар не найден",
                "message": "Возможно, его раскупили или сняли с продажи. "
                           "Загляните в каталог — там есть похожие.",
                "icon":    "fa-box-open",
            }
        if path.startswith("/catalog"):
            return {
                "title":   "Страница каталога не найдена",
                "message": "Такой страницы каталога нет. Откройте каталог заново.",
                "icon":    "fa-bag-shopping",
            }

    if status_code == 500 and path.startswith("/admin/"):
        return {
            "title":   "Ошибка в админке",
            "message": "Что-то сломалось. Попробуйте обновить страницу "
                       "или вернуться к списку товаров.",
            "icon":    "fa-triangle-exclamation",
        }

    return _ERROR_PAGES.get(status_code, {
        "title":   f"Ошибка {status_code}",
        "message": "Что-то пошло не так.",
        "icon":    "fa-circle-exclamation",
    })


def _render_error(
    request: Request,
    status_code: int,
    *,
    force_admin: bool = False,
) -> HTMLResponse:
    preset = _pick_error_preset(status_code, request.url.path)

    is_admin = force_admin or request.url.path.startswith("/admin")
    templates = admin_templates if is_admin else site_templates

    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "error_code":    status_code,
            "error_title":   preset["title"],
            "error_message": preset["message"],
            "error_icon":    preset["icon"],
        },
        status_code=status_code,
    )


@app.exception_handler(NotAuthenticated)
async def not_authenticated_handler(request: Request, exc: NotAuthenticated):
    return RedirectResponse(url="/admin/login", status_code=303)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if _is_ajax(request):
        return JSONResponse(
            {"ok": False, "error": _json_error_message(exc.status_code)},
            status_code=exc.status_code,
        )
    return _render_error(request, exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    if _is_ajax(request):
        return JSONResponse(
            {"ok": False, "error": "Некорректные данные формы."},
            status_code=400,
        )
    if request.url.path.startswith("/product/"):
        return _render_error(request, 404)
    return _render_error(request, 400)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.exception("Необработанная ошибка на %s", request.url.path)

    if _is_ajax(request):
        return JSONResponse(
            {"ok": False, "error": _json_error_message(500)},
            status_code=500,
        )

    try:
        return _render_error(request, 500)
    except Exception:
        log.exception("Рендер error.html тоже упал — отдаём голый текст")
        return HTMLResponse(
            content="500 Internal Server Error",
            status_code=500,
        )


app.include_router(site.router)
app.include_router(auth.router)
app.include_router(catalog.router)
app.include_router(products.router)
app.include_router(site_content.router)