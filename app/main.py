"""Точка сборки приложения.

Здесь только:
  - создание FastAPI();
  - подключение middleware;
  - lifespan (create_all → миграции → seed → прогрев кэша);
  - глобальные exception handlers;
  - регистрация роутеров.

Вся бизнес-логика — в app/routers/*, app/utils/helpers.py, app/data/migrations.py.

Про страницы ошибок:
    Все коды отдают один универсальный шаблон на секцию —
    templates/site/error.html и templates/admin/error.html.
    Какой код что показывает — в словаре _ERROR_PAGES ниже.
    Добавить новый вариант — одна строчка, шаблон трогать не нужно.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import (
    BASE_DIR,
    MAX_UPLOAD_BYTES,
    SECRET_KEY,
    SESSION_HTTPS_ONLY,
    SESSION_MAX_AGE,
    SESSION_SAME_SITE,
    UVICORN_WORKERS,
)
from app.core.database import Base, SessionLocal, engine
from app.core.deps import NotAuthenticated
from app.core.middleware import (
    BodySizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.rendering import admin_templates, site_templates
from app.data import cache
from app.data.migrations import run_startup_migrations
from app.data.seed import seed_database
from app.routers import site
from app.routers.admin import auth, catalog, products

# Папки, без которых приложение не стартует.
(BASE_DIR / "instance").mkdir(exist_ok=True)
(BASE_DIR / "static" / "uploads").mkdir(parents=True, exist_ok=True)


# ============== ЛОГИРОВАНИЕ ==============
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("avelea")


# ============== LIFESPAN ==============
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    if UVICORN_WORKERS > 1:
        log.warning(
            "⚠️  UVICORN_WORKERS=%d. In-memory кэш и rate-limiter работают "
            "только в одном процессе. При нескольких воркерах: "
            "(1) воркеры держат разные копии кэша — invalidate() не "
            "синхронизирует их, сайт может показывать старое; "
            "(2) rate-limit логина обходится (5 попыток на воркер). "
            "Для продакшена — либо один воркер, либо Redis.",
            UVICORN_WORKERS,
        )

    log.info("Запуск: миграции + seed")
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=engine)
        run_startup_migrations(db)
        seed_database(db)
    finally:
        db.close()

    # Прогреваем кэш — чтобы первый публичный запрос уже был быстрым.
    cache.reload_all()
    log.info("Кэш прогрет. Приложение готово")

    yield
    # --- shutdown ---
    log.info("Остановка")


# ============== APP ==============
app = FastAPI(title="Avelea Shop", lifespan=lifespan)

# Порядок middleware в Starlette: тот, кого добавили последним —
# оказывается самым внешним и выполняется первым на запрос.
#
# Здесь: SecurityHeaders (внешний) → BodySize → Session → GZip (внутренний).
# GZip внутри — сжимает тело ответа, а Security добавляет заголовки поверх.
app.add_middleware(GZipMiddleware, minimum_size=800)

app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    https_only=SESSION_HTTPS_ONLY,
    same_site=SESSION_SAME_SITE,
    max_age=SESSION_MAX_AGE,
)
app.add_middleware(
    BodySizeLimitMiddleware,
    max_bytes=MAX_UPLOAD_BYTES + 1024 * 1024,
)
# SecurityHeaders добавляется последним → выполняется первым
# и оборачивает все остальные middleware. Заголовки попадут
# на любой ответ, включая 413 и редиректы сессии.
app.add_middleware(SecurityHeadersMiddleware)

app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)


# ============== HEALTHCHECK ==============
@app.get("/healthz", include_in_schema=False)
async def healthz():
    """Простейший liveness-чек для балансировщика / k8s."""
    return {"ok": True}


# ============== ГЛОБАЛЬНЫЕ ОБРАБОТЧИКИ ==============
#
# Все страницы ошибок живут в одном шаблоне на секцию:
#   templates/admin/error.html
#   templates/site/error.html
#
# Какой код что показывает — в словаре ниже. Хочешь новый
# вариант — добавь строчку, шаблон трогать не нужно.
#
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
        "title": "Такой страницы нет",
        "message": "Возможно, ссылка устарела или в ней опечатка. А может, товар уже раскупили.",
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


def _render_error(
    request: Request,
    status_code: int,
    *,
    force_admin: bool = False,
) -> HTMLResponse:
    """Единая точка рендера страниц ошибок.

    Выбирает шаблон (admin/site) по URL, подставляет пресет
    из _ERROR_PAGES. Незнакомые коды получают нейтральный текст.
    """
    preset = _ERROR_PAGES.get(status_code, {
        "title":   f"Ошибка {status_code}",
        "message": "Что-то пошло не так.",
        "icon":    "fa-circle-exclamation",
    })

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
async def not_auth_handler(request: Request, exc: NotAuthenticated):
    return RedirectResponse(url="/admin/login", status_code=303)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    # Спецслучай: неавторизованный 404 в админке → редирект на логин.
    # Показывать «страницы нет» до логина — плохая идея: это раскрывает
    # структуру админки любому, кто угадывает URL.
    if (
        exc.status_code == 404
        and request.url.path.startswith("/admin")
        and not request.session.get("admin")
    ):
        return RedirectResponse(url="/admin/login", status_code=303)

    return _render_error(request, exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # /product/{id} с нечисловым id → 404 (id не найден), а не 400.
    if request.url.path.startswith("/product/"):
        return _render_error(request, 404)
    return _render_error(request, 400)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Ловит всё, что не поймали предыдущие handler'ы.

    Логируем полный traceback, пользователю показываем нейтральную
    страницу без внутренних деталей.

    Если сам шаблон error.html почему-то упадёт (например, из-за
    опечатки), отдаём голый текст — этого достаточно, чтобы
    не оставить пользователя с пустым ответом.
    """
    log.exception("Необработанная ошибка на %s", request.url.path)
    try:
        return _render_error(request, 500)
    except Exception:
        log.exception("Рендер error.html тоже упал — отдаём голый текст")
        return HTMLResponse(
            content="500 Internal Server Error",
            status_code=500,
        )


# ============== РОУТЕРЫ ==============
app.include_router(site.router)
app.include_router(auth.router)
app.include_router(catalog.router)
app.include_router(products.router)