from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import PlainTextResponse
from sqlalchemy import inspect, text, func
from sqlalchemy.orm import Session
from sqlalchemy.exc import NoSuchTableError
from urllib.parse import urlencode
import sys
import secrets
import re

from app import cache
from app.database import engine, get_db, Base, SessionLocal
from app.models import Product, Brand, Category, product_categories
from app.seed import seed_database
from app.storage import save_image, delete_image
from app.config import (
    SECRET_KEY,
    ADMIN_PASSWORD,
    SESSION_HTTPS_ONLY,
    SESSION_SAME_SITE,
    SESSION_MAX_AGE,
    MAX_UPLOAD_BYTES,
    BASE_DIR,
)

(BASE_DIR / "instance").mkdir(exist_ok=True)
(BASE_DIR / "static" / "uploads").mkdir(parents=True, exist_ok=True)

# Сколько товаров показывать на одной странице каталога.
PER_PAGE = 12

# Сколько товаров показывать на одной странице админского списка.
ADMIN_PRODUCTS_PER_PAGE = 50


# ============== MIDDLEWARE ==============
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


# ============== LIFESPAN / MIGRATIONS ==============
def _migrate_brand_to_fk(db: Session) -> None:
    insp = inspect(engine)
    try:
        product_cols = {c["name"] for c in insp.get_columns("products")}
    except NoSuchTableError:
        return

    if "brand" not in product_cols:
        return

    if "brand_id" not in product_cols:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE products ADD COLUMN brand_id INTEGER "
                "REFERENCES brands(id)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_products_brand_id "
                "ON products (brand_id)"
            ))

    brand_cache: dict[str, Brand] = {
        b.name.lower(): b for b in db.query(Brand).all()
    }

    def get_or_create_brand(name: str) -> Brand:
        key = name.strip().lower()
        if key in brand_cache:
            return brand_cache[key]
        b = Brand(name=name.strip())
        db.add(b)
        db.flush()
        brand_cache[key] = b
        return b

    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, brand FROM products "
            "WHERE brand IS NOT NULL AND brand != ''"
        )).fetchall()

    migrated = 0
    for pid, brand_name in rows:
        product = db.query(Product).filter(Product.id == pid).first()
        if not product:
            continue
        product.brand_id = get_or_create_brand(brand_name).id
        migrated += 1

    if migrated:
        db.commit()
        print(f"✅ Бренды мигрированы у {migrated} товаров")

    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE products DROP COLUMN brand"))
    except Exception as e:
        print(
            f"⚠️  Не удалось удалить products.brand: {e}. "
            f"Колонка больше не используется, но осталась в схеме.",
            file=sys.stderr,
        )


def _migrate_name_lower(db: Session) -> None:
    insp = inspect(engine)
    try:
        product_cols = {c["name"] for c in insp.get_columns("products")}
    except NoSuchTableError:
        return

    if "name_lower" not in product_cols:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE products "
                "ADD COLUMN name_lower VARCHAR(200) NOT NULL DEFAULT ''"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_products_name_lower ON products (name_lower)"
            ))

    updated = 0
    for p in db.query(Product).all():
        expected = (p.name or "").strip().lower()
        if p.name_lower != expected:
            p.name_lower = expected
            updated += 1
    if updated:
        db.commit()


def _migrate_legacy_category_column(db: Session) -> None:
    insp = inspect(engine)
    try:
        product_cols = {c["name"] for c in insp.get_columns("products")}
    except NoSuchTableError:
        return

    if "category" not in product_cols:
        return

    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, category FROM products "
            "WHERE category IS NOT NULL AND category != ''"
        )).fetchall()

    cat_cache: dict[str, Category] = {
        c.name.lower(): c for c in db.query(Category).all()
    }

    def get_or_create_cat(name: str) -> Category:
        key = name.strip().lower()
        if key in cat_cache:
            return cat_cache[key]
        c = Category(name=name.strip())
        db.add(c)
        db.flush()
        cat_cache[key] = c
        return c

    migrated = 0
    for product_id, cat_str in rows:
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            continue

        names = []
        for t in (cat_str or "").split(","):
            t = t.strip()
            if t and t not in names:
                names.append(t)

        product.categories = [get_or_create_cat(n) for n in names]
        migrated += 1

    if migrated:
        db.commit()
        print(f"✅ Категории мигрированы у {migrated} товаров")

    for col in ("category", "tags"):
        if col in product_cols:
            try:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE products DROP COLUMN {col}"))
            except Exception:
                with engine.begin() as conn:
                    conn.execute(text(f"UPDATE products SET {col} = NULL"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=engine)
        _migrate_brand_to_fk(db)
        _migrate_name_lower(db)
        _migrate_legacy_category_column(db)
        seed_database(db)
    finally:
        db.close()

    # Прогреваем кэш — чтобы первый публичный запрос уже был быстрым.
    cache.reload_all()

    yield
    # --- shutdown ---


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
app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)


# ============== АВТОРИЗАЦИЯ ==============
class NotAuthenticated(Exception):
    pass


@app.exception_handler(NotAuthenticated)
async def not_auth_handler(request: Request, exc: NotAuthenticated):
    return RedirectResponse(url="/admin/login", status_code=303)


def _safe_str_compare(a: str, b: str) -> bool:
    try:
        return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
    except (TypeError, ValueError):
        return False


def get_csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


async def _check_csrf(request: Request) -> None:
    form = await request.form()
    token = form.get("csrf_token")
    session_token = request.session.get("csrf_token")

    if not token or not session_token:
        raise HTTPException(status_code=403, detail="CSRF token invalid")

    if not _safe_str_compare(str(token), str(session_token)):
        raise HTTPException(status_code=403, detail="CSRF token invalid")


async def require_admin(request: Request):
    if not request.session.get("admin"):
        raise NotAuthenticated()
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        await _check_csrf(request)
    return True


# ============== ХЕЛПЕРЫ ==============
def build_filter_url(params, remove_key: str, remove_value: str = None) -> str:
    pairs = []
    for k in params.keys():
        for v in params.getlist(k):
            if k == remove_key and (remove_value is None or v == remove_value):
                continue
            pairs.append((k, v))
    qs = urlencode(pairs)
    return "/catalog" + ("?" + qs if qs else "")


def build_page_url(params, page_num: int, base_path: str = "/catalog") -> str:
    pairs = []
    for k in params.keys():
        if k == "page":
            continue
        for v in params.getlist(k):
            pairs.append((k, v))
    pairs.append(("page", str(page_num)))
    return base_path + "?" + urlencode(pairs)


def build_reset_url() -> str:
    return "/catalog"


def make_page_items(current: int, total: int, params, base_path: str = "/catalog"):
    if total <= 1:
        return []
    if total <= 7:
        raw = list(range(1, total + 1))
    else:
        raw_set = sorted({1, total, current - 1, current, current + 1})
        raw = []
        prev = 0
        for p in raw_set:
            if 1 <= p <= total:
                if p - prev > 1:
                    raw.append(None)
                raw.append(p)
                prev = p

    items = []
    for p in raw:
        if p is None:
            items.append({"ellipsis": True})
        else:
            items.append({
                "num": p,
                "url": build_page_url(params, p, base_path),
                "current": (p == current),
            })
    return items


def _resolve_categories(db: Session, names: list[str]) -> list[Category]:
    if not names:
        return []
    return db.query(Category).filter(Category.name.in_(names)).all()


def _resolve_brand_id(db: Session, raw: str) -> int | None:
    raw = (raw or "").strip()
    if not raw or not raw.isdigit():
        return None
    bid = int(raw)
    exists = db.query(Brand).filter(Brand.id == bid).first()
    return bid if exists else None


def _validate_price(price: int) -> str | None:
    if price < 0:
        return "Цена не может быть отрицательной — изменения не сохранены."
    return None


def _parse_volume(volume: str | None) -> tuple[str, str]:
    if not volume:
        return "", "мл"

    m = re.match(r"^\s*([\d.,]+)\s*([а-яa-z]*)\s*$", volume, re.IGNORECASE)
    if not m:
        return "", "мл"

    amount = m.group(1).replace(",", ".")
    unit = (m.group(2) or "").strip().lower()

    if unit in ("г", "гр", "g", "gr", "gram"):
        unit = "г"
    else:
        unit = "мл"

    return amount, unit


def _product_form_context(db: Session, product: Product | None):
    volume_amount, volume_unit = _parse_volume(product.volume if product else None)
    return {
        "product": product,
        "product_categories": [c.name for c in product.categories] if product else [],
        "all_categories": cache.get_categories(),
        "all_brands": cache.get_brands(),
        "volume_amount": volume_amount,
        "volume_unit": volume_unit,
    }


# ============== ШАБЛОНЫ ==============
site_templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates" / "site")
admin_templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates" / "admin")

site_templates.env.globals["build_page_url"] = build_page_url
site_templates.env.globals["build_filter_url"] = build_filter_url
site_templates.env.globals["build_reset_url"] = build_reset_url

site_templates.env.globals["csrf_token"] = get_csrf_token
admin_templates.env.globals["csrf_token"] = get_csrf_token


# ============== ГЛОБАЛЬНЫЕ ОБРАБОТЧИКИ ==============
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


# ==================================================
# ==============  ПУБЛИЧНАЯ ЧАСТЬ  =================
# ==================================================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    products = cache.get_products()
    categories = cache.get_categories()

    popular = [p for p in products if p.popular][:6]

    return site_templates.TemplateResponse(request, "index.html", {
        "popular": popular,
        "categories": categories,
    })


@app.get("/catalog", response_class=HTMLResponse)
async def catalog(request: Request):
    params = request.query_params

    q = (params.get("q") or "").strip().lower()
    selected_categories = set(params.getlist("category"))
    selected_brands = set(params.getlist("brand"))
    price_min = params.get("price_min") or ""
    price_max = params.get("price_max") or ""
    sort = params.get("sort") or ""

    try:
        page = int(params.get("page") or 1)
    except ValueError:
        page = 1
    if page < 1:
        page = 1

    all_products = cache.get_products()
    all_categories = cache.get_categories()
    all_brands_used = cache.get_brand_names()

    # ---------- Фильтрация ----------
    filtered = []
    for p in all_products:
        if q and q not in p.name_lower:
            continue

        if selected_categories:
            p_cats = {c.name for c in p.categories}
            if not (p_cats & selected_categories):
                continue

        if selected_brands:
            if not p.brand or p.brand not in selected_brands:
                continue

        if price_min:
            try:
                if p.price < int(price_min):
                    continue
            except ValueError:
                pass

        if price_max:
            try:
                if p.price > int(price_max):
                    continue
            except ValueError:
                pass

        filtered.append(p)

    # ---------- Сортировка ----------
    if sort == "price_asc":
        filtered.sort(key=lambda p: p.price)
    elif sort == "price_desc":
        filtered.sort(key=lambda p: p.price, reverse=True)
    elif sort == "name":
        filtered.sort(key=lambda p: p.name.lower())
    elif sort == "popular":
        filtered.sort(key=lambda p: (not p.popular, p.id))
    else:
        filtered.sort(key=lambda p: p.id)

    # ---------- Пагинация ----------
    total_count = len(filtered)
    total_pages = max(1, (total_count + PER_PAGE - 1) // PER_PAGE)
    if page > total_pages:
        page = total_pages

    start = (page - 1) * PER_PAGE
    end = start + PER_PAGE
    products = filtered[start:end]

    # ---------- Данные для фильтров ----------
    # В каталоге список брендов — только те, у которых есть товары.
    category_names = [c.name for c in all_categories]

    # ---------- Чипы активных фильтров ----------
    active_filters = []
    if q:
        active_filters.append({
            "label": f"Поиск: {params.get('q')}",
            "remove_url": build_filter_url(params, "q"),
        })
    for c in selected_categories:
        active_filters.append({"label": c, "remove_url": build_filter_url(params, "category", c)})
    for b in selected_brands:
        active_filters.append({"label": b, "remove_url": build_filter_url(params, "brand", b)})
    if price_min:
        active_filters.append({"label": f"от {price_min} ₽", "remove_url": build_filter_url(params, "price_min")})
    if price_max:
        active_filters.append({"label": f"до {price_max} ₽", "remove_url": build_filter_url(params, "price_max")})

    start_idx = start + 1 if total_count else 0
    end_idx = min(end, total_count)

    return site_templates.TemplateResponse(request, "catalog.html", {
        "products": products,
        "total_count": total_count,
        "start_idx": start_idx,
        "end_idx": end_idx,
        "categories": category_names,
        "brands": all_brands_used,
        "selected_categories": list(selected_categories),
        "selected_brands": list(selected_brands),
        "price_min": price_min,
        "price_max": price_max,
        "q": params.get("q") or "",
        "sort": sort,
        "page": page,
        "total_pages": total_pages,
        "page_items": make_page_items(page, total_pages, params),
        "active_filters": active_filters,
        "reset_url": build_reset_url(),
    })


@app.get("/product/{product_id}", response_class=HTMLResponse)
async def product_page(request: Request, product_id: int):
    all_products = cache.get_products()

    product = next((p for p in all_products if p.id == product_id), None)
    if not product:
        return site_templates.TemplateResponse(request, "404.html", status_code=404)

    cat_names = {c.name for c in product.categories}
    similar = [
        p for p in all_products
        if p.id != product.id and ({c.name for c in p.categories} & cat_names)
    ][:6]

    return site_templates.TemplateResponse(request, "product.html", {
        "product": product,
        "product_categories": [c.name for c in product.categories],
        "similar": similar,
    })


@app.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    return site_templates.TemplateResponse(request, "about.html")


# ==================================================
# ==============  АДМИНКА: АВТОРИЗАЦИЯ  ============
# ==================================================

@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_form(request: Request):
    if request.session.get("admin"):
        return RedirectResponse(url="/admin/products", status_code=303)
    return admin_templates.TemplateResponse(request, "login.html", {
        "error": None,
    })


@app.post("/admin/login", dependencies=[Depends(_check_csrf)])
async def admin_login_submit(request: Request, password: str = Form(...)):
    if _safe_str_compare(password, ADMIN_PASSWORD):
        request.session["admin"] = True
        return RedirectResponse(url="/admin/products", status_code=303)
    return admin_templates.TemplateResponse(
        request, "login.html", {"error": "Неверный пароль"}, status_code=401,
    )


@app.get("/admin/logout")
async def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
async def admin_root(request: Request):
    return RedirectResponse(url="/admin/products", status_code=303)


# ==================================================
# ==============  АДМИНКА: ТОВАРЫ  =================
# ==================================================

@app.get("/admin/products", response_class=HTMLResponse)
async def admin_products(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
):
    params = request.query_params
    q = (params.get("q") or "").strip()

    try:
        page = int(params.get("page") or 1)
    except ValueError:
        page = 1
    if page < 1:
        page = 1

    # Админка работает с БД напрямую — здесь кэш не нужен, важна свежесть.
    query = db.query(Product)
    if q:
        query = query.filter(Product.name_lower.contains(q.lower()))
    query = query.order_by(Product.id.desc())

    total_count = query.count()
    total_pages = max(
        1,
        (total_count + ADMIN_PRODUCTS_PER_PAGE - 1) // ADMIN_PRODUCTS_PER_PAGE,
    )
    if page > total_pages:
        page = total_pages

    products = (
        query
        .offset((page - 1) * ADMIN_PRODUCTS_PER_PAGE)
        .limit(ADMIN_PRODUCTS_PER_PAGE)
        .all()
    )

    start_idx = (page - 1) * ADMIN_PRODUCTS_PER_PAGE + 1 if total_count else 0
    end_idx = min(page * ADMIN_PRODUCTS_PER_PAGE, total_count)

    flash_error = request.session.pop("flash_error", None)

    return admin_templates.TemplateResponse(request, "products.html", {
        "products": products,
        "all_categories": cache.get_categories(),
        "all_brands": cache.get_brands(),
        "q": q,
        "page": page,
        "total_pages": total_pages,
        "total_count": total_count,
        "start_idx": start_idx,
        "end_idx": end_idx,
        "page_items": make_page_items(page, total_pages, params, "/admin/products"),
        "prev_url": (
            build_page_url(params, page - 1, "/admin/products") if page > 1 else None
        ),
        "next_url": (
            build_page_url(params, page + 1, "/admin/products") if page < total_pages else None
        ),
        "flash_error": flash_error,
    })


@app.get("/admin/products/new", response_class=HTMLResponse)
async def admin_product_new(request: Request, _: bool = Depends(require_admin)):
    return RedirectResponse(url="/admin/products", status_code=303)


@app.post("/admin/products/new")
async def admin_product_create(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
    name: str = Form(...),
    categories: list[str] = Form([]),
    brand_id: str = Form(...),
    price: int = Form(...),
    volume_amount: str = Form(...),
    volume_unit: str = Form(...),
    description: str = Form(...),
    popular: str = Form(None),
    image: UploadFile = File(...),
):
    if (err := _validate_price(price)) is not None:
        request.session["flash_error"] = err
        return RedirectResponse(url="/admin/products", status_code=303)

    if not categories:
        request.session["flash_error"] = (
            "Выберите хотя бы одну категорию — товар не создан."
        )
        return RedirectResponse(url="/admin/products", status_code=303)

    if not brand_id or not brand_id.strip():
        request.session["flash_error"] = "Выберите бренд — товар не создан."
        return RedirectResponse(url="/admin/products", status_code=303)

    image_url, img_err = save_image(image)
    if img_err:
        request.session["flash_error"] = img_err

    volume_str = (
        f"{volume_amount.strip()} {volume_unit.strip()}"
        if volume_amount.strip() else None
    )

    product = Product(
        name=name.strip(),
        brand_id=_resolve_brand_id(db, brand_id),
        price=price,
        volume=volume_str,
        description=description.strip() or None,
        popular=bool(popular),
        image=image_url,
    )
    product.categories = _resolve_categories(db, categories)

    db.add(product)
    db.commit()

    # Свежие данные — сбрасываем кэш, публичная часть перечитает при следующем запросе.
    cache.invalidate()

    return RedirectResponse(url="/admin/products", status_code=303)


@app.get("/admin/products/{product_id}/edit", response_class=HTMLResponse)
async def admin_product_edit(
    request: Request,
    product_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404)
    ctx = _product_form_context(db, product)

    if request.headers.get("hx-request") == "true":
        ctx["in_dialog"] = True
        return admin_templates.TemplateResponse(request, "_product_form.html", ctx)

    return admin_templates.TemplateResponse(request, "product_form.html", ctx)


@app.post("/admin/products/{product_id}/edit")
async def admin_product_update(
    request: Request,
    product_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
    name: str = Form(...),
    categories: list[str] = Form([]),
    brand_id: str = Form(...),
    price: int = Form(...),
    volume_amount: str = Form(...),
    volume_unit: str = Form(...),
    description: str = Form(...),
    popular: str = Form(None),
    image: UploadFile = File(None),
    remove_image: str = Form(None),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404)

    if (err := _validate_price(price)) is not None:
        request.session["flash_error"] = err
        return RedirectResponse(url="/admin/products", status_code=303)

    if not categories:
        request.session["flash_error"] = (
            "Выберите хотя бы одну категорию — изменения не сохранены."
        )
        return RedirectResponse(url="/admin/products", status_code=303)

    if not brand_id or not brand_id.strip():
        request.session["flash_error"] = (
            "Выберите бренд — изменения не сохранены."
        )
        return RedirectResponse(url="/admin/products", status_code=303)

    product.name = name.strip()
    product.brand_id = _resolve_brand_id(db, brand_id)
    product.price = price
    product.volume = (
        f"{volume_amount.strip()} {volume_unit.strip()}"
        if volume_amount.strip() else None
    )
    product.description = description.strip() or None
    product.popular = bool(popular)

    product.categories = _resolve_categories(db, categories)

    old_image = product.image
    new_image, img_err = save_image(image)
    if img_err:
        request.session["flash_error"] = img_err

    if new_image:
        final_image = new_image
    elif remove_image:
        final_image = None
    else:
        final_image = old_image

    product.image = final_image
    db.commit()

    if old_image and old_image != final_image:
        delete_image(old_image)

    cache.invalidate()

    return RedirectResponse(url="/admin/products", status_code=303)


@app.post("/admin/products/{product_id}/delete")
async def admin_product_delete(
    request: Request,
    product_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if product:
        old_image = product.image
        db.delete(product)
        db.commit()
        delete_image(old_image)
        cache.invalidate()
    return RedirectResponse(url="/admin/products", status_code=303)


# ==================================================
# ==============  АДМИНКА: КАТЕГОРИИ  ==============
# ==================================================

@app.get("/admin/categories", response_class=HTMLResponse)
async def admin_categories(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
):
    categories = db.query(Category).order_by(Category.name).all()

    counts = dict(
        db.query(
            product_categories.c.category_id,
            func.count(product_categories.c.product_id),
        )
        .group_by(product_categories.c.category_id)
        .all()
    )

    flash_error = request.session.pop("flash_error", None)

    return admin_templates.TemplateResponse(request, "categories.html", {
        "categories": categories,
        "counts": counts,
        "flash_error": flash_error,
    })


@app.post("/admin/categories/new")
async def admin_category_create(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
    name: str = Form(...),
):
    name = name.strip()
    if name:
        exists = db.query(Category).filter(Category.name == name).first()
        if exists:
            request.session["flash_error"] = f"Категория «{name}» уже существует."
        else:
            db.add(Category(name=name))
            db.commit()
            cache.invalidate()
    return RedirectResponse(url="/admin/categories", status_code=303)


@app.post("/admin/categories/{category_id}/edit")
async def admin_category_edit(
    request: Request,
    category_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
    name: str = Form(...),
):
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404)

    name = name.strip()
    if name and name != category.name:
        exists = (
            db.query(Category)
              .filter(Category.name == name, Category.id != category_id)
              .first()
        )
        if exists:
            request.session["flash_error"] = f"Категория «{name}» уже существует."
        else:
            category.name = name
            db.commit()
            cache.invalidate()
    return RedirectResponse(url="/admin/categories", status_code=303)


@app.post("/admin/categories/{category_id}/delete")
async def admin_category_delete(
    request: Request,
    category_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
):
    category = db.query(Category).filter(Category.id == category_id).first()
    if category:
        db.delete(category)
        db.commit()
        cache.invalidate()
    return RedirectResponse(url="/admin/categories", status_code=303)


# ==================================================
# ==============  АДМИНКА: БРЕНДЫ  =================
# ==================================================

@app.get("/admin/brands", response_class=HTMLResponse)
async def admin_brands(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
):
    brands = db.query(Brand).order_by(Brand.name).all()

    counts = dict(
        db.query(Product.brand_id, func.count(Product.id))
          .filter(Product.brand_id.isnot(None))
          .group_by(Product.brand_id)
          .all()
    )

    flash_error = request.session.pop("flash_error", None)

    return admin_templates.TemplateResponse(request, "brands.html", {
        "brands": brands,
        "counts": counts,
        "flash_error": flash_error,
    })


@app.post("/admin/brands/new")
async def admin_brand_create(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
    name: str = Form(...),
):
    name = name.strip()
    if name:
        exists = db.query(Brand).filter(Brand.name == name).first()
        if exists:
            request.session["flash_error"] = f"Бренд «{name}» уже существует."
        else:
            db.add(Brand(name=name))
            db.commit()
            cache.invalidate()
    return RedirectResponse(url="/admin/brands", status_code=303)


@app.post("/admin/brands/{brand_id}/edit")
async def admin_brand_edit(
    request: Request,
    brand_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
    name: str = Form(...),
):
    brand = db.query(Brand).filter(Brand.id == brand_id).first()
    if not brand:
        raise HTTPException(status_code=404)

    name = name.strip()
    if name and name != brand.name:
        exists = (
            db.query(Brand)
              .filter(Brand.name == name, Brand.id != brand_id)
              .first()
        )
        if exists:
            request.session["flash_error"] = f"Бренд «{name}» уже существует."
        else:
            brand.name = name
            db.commit()
            cache.invalidate()
    return RedirectResponse(url="/admin/brands", status_code=303)


@app.post("/admin/brands/{brand_id}/delete")
async def admin_brand_delete(
    request: Request,
    brand_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
):
    brand = db.query(Brand).filter(Brand.id == brand_id).first()
    if brand:
        for p in db.query(Product).filter(Product.brand_id == brand.id).all():
            p.brand_id = None
        db.delete(brand)
        db.commit()
        cache.invalidate()
    return RedirectResponse(url="/admin/brands", status_code=303)