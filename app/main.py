from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import NoSuchTableError
from urllib.parse import urlencode
from pathlib import Path
import os
import secrets
import uuid

from app.database import engine, get_db, Base
from app.models import Product, Brand, Category, product_categories
from app.seed import seed_database
from app.config import SECRET_KEY, ADMIN_PASSWORD

os.makedirs("instance", exist_ok=True)
os.makedirs("static/uploads", exist_ok=True)

# Сколько товаров показывать на одной странице каталога.
PER_PAGE = 12

# Максимальный размер загружаемой картинки — 5 МБ.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

# Сигнатуры (magic bytes) допустимых форматов. Расширение из имени файла
# НЕ используется — определяем формат по содержимому.
_MAGIC = (
    (b"\xff\xd8\xff",          ".jpg"),
    (b"\x89PNG\r\n\x1a\n",     ".png"),
    (b"GIF87a",                ".gif"),
    (b"GIF89a",                ".gif"),
)


# ============== LIFESPAN ==============
def _migrate_legacy_category_column(db: Session) -> None:
    """Миграция старой колонки products.category → many-to-many.

    Выполняется только если в БД реально осталась старая колонка.
    """
    insp = inspect(engine)
    try:
        product_cols = {c["name"] for c in insp.get_columns("products")}
    except NoSuchTableError:
        return

    if "category" not in product_cols:
        return

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, category FROM products "
                "WHERE category IS NOT NULL AND category != ''"
            )
        ).fetchall()

    # Кеш категорий в Python — потому что SQLite LOWER() не знает кириллицу
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

    # Снести старые колонки (SQLite 3.35+), иначе просто обнулить
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
    db = next(get_db())
    try:
        Base.metadata.create_all(bind=engine)
        _migrate_legacy_category_column(db)
        seed_database(db)
    finally:
        db.close()
    yield
    # --- shutdown --- (пока ничего не нужно)


app = FastAPI(title="Avelea Shop", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ============== АВТОРИЗАЦИЯ ==============
class NotAuthenticated(Exception):
    pass


@app.exception_handler(NotAuthenticated)
async def not_auth_handler(request: Request, exc: NotAuthenticated):
    return RedirectResponse(url="/admin/login", status_code=303)


def get_csrf_token(request: Request) -> str:
    """Возвращает CSRF-токен текущей сессии, создавая при необходимости."""
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


async def _check_csrf(request: Request) -> None:
    """Проверяет csrf_token из формы против токена в сессии.

    Starlette кеширует request.form(), поэтому повторное чтение формы
    в самом обработчике (через Form(...)) безопасно."""
    form = await request.form()
    token = form.get("csrf_token")
    session_token = request.session.get("csrf_token")
    if (
        not token
        or not session_token
        or not secrets.compare_digest(str(token), str(session_token))
    ):
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


def build_page_url(params, page_num: int) -> str:
    pairs = []
    for k in params.keys():
        if k == "page":
            continue
        for v in params.getlist(k):
            pairs.append((k, v))
    pairs.append(("page", str(page_num)))
    return "/catalog?" + urlencode(pairs)


def build_reset_url() -> str:
    return "/catalog"


def make_page_items(current: int, total: int, params):
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
                "url": build_page_url(params, p),
                "current": (p == current),
            })
    return items


def _sniff_image_ext(head: bytes) -> str | None:
    """Определяет расширение по magic bytes. None — если формат не поддерживается."""
    for magic, ext in _MAGIC:
        if head.startswith(magic):
            return ext
    # WebP: "RIFF" .... "WEBP"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    return None


def _save_upload(file: UploadFile | None) -> str | None:
    """Сохраняет картинку в static/uploads и возвращает URL.

    Возвращает None, если файл пуст, слишком большой или не является
    картинкой поддерживаемого формата. Расширение берётся из magic bytes,
    имя файла из запроса игнорируется — это защищает от подмены расширения.
    """
    if not file or not file.filename:
        return None

    content = file.file.read()
    if not content:
        return None
    if len(content) > MAX_UPLOAD_BYTES:
        return None

    ext = _sniff_image_ext(content[:16])
    if ext is None:
        return None

    name = f"{uuid.uuid4().hex}{ext}"
    dest = Path("static/uploads") / name
    with dest.open("wb") as f:
        f.write(content)
    return f"/static/uploads/{name}"


def _delete_upload(image_url: str | None) -> None:
    """Удаляет файл из static/uploads по URL вида /static/uploads/<name>.

    Молча игнорирует всё, что не совпадает с ожидаемым префиксом —
    чтобы случайно не снести что-то вне папки загрузок.
    """
    if not image_url or not image_url.startswith("/static/uploads/"):
        return
    name = image_url.rsplit("/", 1)[-1]
    if not name or "/" in name or ".." in name:
        return
    path = Path("static/uploads") / name
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _resolve_categories(db: Session, names: list[str]) -> list[Category]:
    """Превращает список имён категорий в список ORM-объектов Category.
    Имена, которых нет в БД, молча игнорируются."""
    if not names:
        return []
    return db.query(Category).filter(Category.name.in_(names)).all()


# ============== ШАБЛОНЫ ==============
site_templates = Jinja2Templates(directory="app/templates/site")
admin_templates = Jinja2Templates(directory="app/templates/admin")

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
                "404.html", {"request": request}, status_code=404,
            )
        return site_templates.TemplateResponse(
            "404.html", {"request": request}, status_code=404,
        )
    return HTMLResponse(content=str(exc.detail), status_code=exc.status_code)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/product/"):
        return site_templates.TemplateResponse("404.html", {"request": request}, status_code=404)
    return HTMLResponse(content="Bad request", status_code=400)


# ============== ГЛАВНАЯ ==============
@app.get("/", response_class=HTMLResponse)
async def index(request: Request, db: Session = Depends(get_db)):
    popular = db.query(Product).filter(Product.popular == True).limit(6).all()
    return site_templates.TemplateResponse("index.html", {
        "request": request,
        "popular": popular,
    })


# ============== КАТАЛОГ ==============
@app.get("/catalog", response_class=HTMLResponse)
async def catalog(request: Request, db: Session = Depends(get_db)):
    params = request.query_params

    q = (params.get("q") or "").strip()
    selected_categories = params.getlist("category")
    selected_brands = params.getlist("brand")
    price_min = params.get("price_min") or ""
    price_max = params.get("price_max") or ""
    sort = params.get("sort") or ""

    try:
        page = int(params.get("page") or 1)
    except ValueError:
        page = 1
    if page < 1:
        page = 1

    query = db.query(Product)

    if q:
        query = query.filter(Product.name.ilike(f"%{q}%"))

    if selected_categories:
        query = query.filter(
            Product.categories.any(Category.name.in_(selected_categories))
        )

    if selected_brands:
        query = query.filter(Product.brand.in_(selected_brands))

    if price_min:
        try:
            query = query.filter(Product.price >= int(price_min))
        except ValueError:
            pass
    if price_max:
        try:
            query = query.filter(Product.price <= int(price_max))
        except ValueError:
            pass

    if sort == "price_asc":
        query = query.order_by(Product.price.asc())
    elif sort == "price_desc":
        query = query.order_by(Product.price.desc())
    elif sort == "name":
        query = query.order_by(Product.name.asc())
    elif sort == "popular":
        query = query.order_by(Product.popular.desc(), Product.id.asc())
    else:
        query = query.order_by(Product.id.asc())

    total_count = query.count()
    total_pages = max(1, (total_count + PER_PAGE - 1) // PER_PAGE)
    if page > total_pages:
        page = total_pages

    products = query.offset((page - 1) * PER_PAGE).limit(PER_PAGE).all()

    all_categories = [c.name for c in db.query(Category).order_by(Category.name).all()]
    all_brands = [b[0] for b in db.query(Product.brand).distinct().all() if b[0]]

    active_filters = []
    if q:
        active_filters.append({"label": f"Поиск: {q}", "remove_url": build_filter_url(params, "q")})
    for c in selected_categories:
        active_filters.append({"label": c, "remove_url": build_filter_url(params, "category", c)})
    for b in selected_brands:
        active_filters.append({"label": b, "remove_url": build_filter_url(params, "brand", b)})
    if price_min:
        active_filters.append({"label": f"от {price_min} ₽", "remove_url": build_filter_url(params, "price_min")})
    if price_max:
        active_filters.append({"label": f"до {price_max} ₽", "remove_url": build_filter_url(params, "price_max")})

    start_idx = (page - 1) * PER_PAGE + 1 if total_count else 0
    end_idx = min(page * PER_PAGE, total_count)

    return site_templates.TemplateResponse("catalog.html", {
        "request": request,
        "products": products,
        "total_count": total_count,
        "start_idx": start_idx,
        "end_idx": end_idx,
        "categories": all_categories,
        "brands": all_brands,
        "selected_categories": selected_categories,
        "selected_brands": selected_brands,
        "price_min": price_min,
        "price_max": price_max,
        "q": q,
        "sort": sort,
        "page": page,
        "total_pages": total_pages,
        "page_items": make_page_items(page, total_pages, params),
        "active_filters": active_filters,
        "reset_url": build_reset_url(),
    })


# ============== СТРАНИЦА ТОВАРА ==============
@app.get("/product/{product_id}", response_class=HTMLResponse)
async def product_page(request: Request, product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return site_templates.TemplateResponse("404.html", {"request": request}, status_code=404)
    return site_templates.TemplateResponse("product.html", {
        "request": request,
        "product": product,
        "product_categories": [c.name for c in product.categories],
    })


# ============== О НАС ==============
@app.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    return site_templates.TemplateResponse("about.html", {"request": request})


# ==================================================
# ==============  АДМИНКА: АВТОРИЗАЦИЯ  ============
# ==================================================

@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_form(request: Request):
    if request.session.get("admin"):
        return RedirectResponse(url="/admin/products", status_code=303)
    return admin_templates.TemplateResponse("login.html", {
        "request": request,
        "error": None,
    })


@app.post("/admin/login", dependencies=[Depends(_check_csrf)])
async def admin_login_submit(request: Request, password: str = Form(...)):
    if secrets.compare_digest(password, ADMIN_PASSWORD):
        request.session["admin"] = True
        return RedirectResponse(url="/admin/products", status_code=303)
    return admin_templates.TemplateResponse("login.html", {
        "request": request,
        "error": "Неверный пароль",
    }, status_code=401)


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
async def admin_products(request: Request, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    products = db.query(Product).order_by(Product.id.desc()).all()
    return admin_templates.TemplateResponse("products.html", {
        "request": request,
        "products": products,
        "all_categories": db.query(Category).order_by(Category.name).all(),
        "all_brands": db.query(Brand).order_by(Brand.name).all(),
    })


def _product_form_context(db: Session, product: Product | None):
    return {
        "product": product,
        "product_categories": [c.name for c in product.categories] if product else [],
        "all_categories": db.query(Category).order_by(Category.name).all(),
        "all_brands": db.query(Brand).order_by(Brand.name).all(),
    }


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
    brand: str = Form(""),
    price: int = Form(...),
    volume: str = Form(""),
    description: str = Form(""),
    popular: str = Form(None),
    image: UploadFile = File(None),
):
    image_url = _save_upload(image)

    product = Product(
        name=name.strip(),
        brand=brand.strip() or None,
        price=price,
        volume=volume.strip() or None,
        description=description.strip() or None,
        popular=bool(popular),
        image=image_url,
    )
    product.categories = _resolve_categories(db, categories)

    db.add(product)
    db.commit()
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
    ctx["request"] = request
    return admin_templates.TemplateResponse("product_form.html", ctx)


@app.post("/admin/products/{product_id}/edit")
async def admin_product_update(
    request: Request,
    product_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
    name: str = Form(...),
    categories: list[str] = Form([]),
    brand: str = Form(""),
    price: int = Form(...),
    volume: str = Form(""),
    description: str = Form(""),
    popular: str = Form(None),
    image: UploadFile = File(None),
    remove_image: str = Form(None),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404)

    product.name = name.strip()
    product.brand = brand.strip() or None
    product.price = price
    product.volume = volume.strip() or None
    product.description = description.strip() or None
    product.popular = bool(popular)

    # Полностью заменяем набор категорий
    product.categories = _resolve_categories(db, categories)

    # Логика с картинкой:
    #   новый файл        → берём его, старый удаляем;
    #   remove_image      → стираем старую, ставим None;
    #   ни то, ни другое  → оставляем как было.
    old_image = product.image
    new_image = _save_upload(image)

    if new_image:
        final_image = new_image
    elif remove_image:
        final_image = None
    else:
        final_image = old_image

    if old_image and old_image != final_image:
        _delete_upload(old_image)

    product.image = final_image

    db.commit()
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
        _delete_upload(product.image)
        db.delete(product)
        db.commit()
    return RedirectResponse(url="/admin/products", status_code=303)


# ==================================================
# ==============  АДМИНКА: КАТЕГОРИИ  ==============
# ==================================================

@app.get("/admin/categories", response_class=HTMLResponse)
async def admin_categories(request: Request, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    categories = db.query(Category).order_by(Category.name).all()
    counts = {c.name: len(c.products) for c in categories}

    return admin_templates.TemplateResponse("categories.html", {
        "request": request,
        "categories": categories,
        "counts": counts,
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
        if not exists:
            db.add(Category(name=name))
            db.commit()
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
    return RedirectResponse(url="/admin/categories", status_code=303)


# ==================================================
# ==============  АДМИНКА: БРЕНДЫ  =================
# ==================================================

@app.get("/admin/brands", response_class=HTMLResponse)
async def admin_brands(request: Request, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    brands = db.query(Brand).order_by(Brand.name).all()

    counts = {}
    for (b,) in db.query(Product.brand).all():
        if b:
            counts[b] = counts.get(b, 0) + 1

    return admin_templates.TemplateResponse("brands.html", {
        "request": request,
        "brands": brands,
        "counts": counts,
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
        if not exists:
            db.add(Brand(name=name))
            db.commit()
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
        for p in db.query(Product).filter(Product.brand == brand.name).all():
            p.brand = None
        db.delete(brand)
        db.commit()
    return RedirectResponse(url="/admin/brands", status_code=303)