"""Точка сборки приложения.

Здесь только:
  - создание FastAPI();
  - подключение middleware;
  - lifespan (create_all → миграции → seed → прогрев кэша);
  - глобальные exception handlers;
  - регистрация роутеров.

Вся бизнес-логика — в app/routers/*, app/utils/helpers.py, app/data/migrations.py.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
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
@app.exception_handler(NotAuthenticated)
async def not_auth_handler(request: Request, exc: NotAuthenticated):
    return RedirectResponse(url="/admin/login", status_code=303)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        if request.url.path.startswith("/admin"):
            if not request.session.get("admin"):
                return RedirectResponse(url="/admin/login", status_code=303)
            return admin_templates.TemplateResponse(
                request, "404.html", status_code=404,
            )
        return site_templates.TemplateResponse(
            request, "404.html", status_code=404,
        )
    return HTMLResponse(content=str(exc.detail), status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/product/"):
        return site_templates.TemplateResponse(request, "404.html", status_code=404)
    return HTMLResponse(content="Bad request", status_code=400)


# ============== РОУТЕРЫ ==============
app.include_router(site.router)
app.include_router(auth.router)
app.include_router(catalog.router)
app.include_router(products.router)