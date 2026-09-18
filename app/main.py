from fastapi import FastAPI, Request, Depends, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import or_
from sqlalchemy.orm import Session
from urllib.parse import urlencode
from pathlib import Path
import os
import secrets
import uuid

from app.database import engine, get_db, Base
from app.models import Product, Brand, Category
from app.config import SECRET_KEY, ADMIN_PASSWORD

os.makedirs("instance", exist_ok=True)
os.makedirs("static/uploads", exist_ok=True)
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Avelea Shop")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="app/templates")

ALLOWED_PER_PAGE = (12, 24, 48)
ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


# ============== АВТОРИЗАЦИЯ ==============
class NotAuthenticated(Exception):
    pass


@app.exception_handler(NotAuthenticated)
async def not_auth_handler(request: Request, exc: NotAuthenticated):
    return RedirectResponse(url="/admin/login", status_code=303)


def require_admin(request: Request):
    if not request.session.get("admin"):
        raise NotAuthenticated()
    return True


# ============== ХЕЛПЕРЫ ==============
def _parse_list(s: str | None) -> list[str]:
    if not s:
        return []
    seen = []
    for t in s.split(","):
        t = t.strip()
        if t and t not in seen:
            seen.append(t)
    return seen


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


def build_reset_url(view: str, per_page: int) -> str:
    keep = []
    if view != "grid":
        keep.append(("view", view))
    if per_page != ALLOWED_PER_PAGE[0]:
        keep.append(("per_page", str(per_page)))
    return "/catalog" + ("?" + urlencode(keep) if keep else "")


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


def _save_upload(file: UploadFile) -> str | None:
    if not file or not file.filename:
        return None
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXT:
        return None
    name = f"{uuid.uuid4().hex}{ext}"
    dest = Path("static/uploads") / name
    with dest.open("wb") as f:
        f.write(file.file.read())
    return f"/static/uploads/{name}"


def _remove_category_from_all_products(db: Session, name: str):
    for p in db.query(Product).all():
        cats = _parse_list(p.category)
        if name in cats:
            cats = [x for x in cats if x != name]
            p.category = ",".join(cats) if cats else None


# ============== ГЛОБАЛЬНЫЕ ОБРАБОТЧИКИ ==============
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)
    return HTMLResponse(content=str(exc.detail), status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/product/"):
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)
    return HTMLResponse(content="Bad request", status_code=400)


# ============== ГЛАВНАЯ ==============
@app.get("/", response_class=HTMLResponse)
async def index(request: Request, db: Session = Depends(get_db)):
    popular = db.query(Product).filter(Product.popular == True).limit(6).all()
    return templates.TemplateResponse("index.html", {
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

    view = params.get("view") or "grid"
    if view not in ("grid", "list"):
        view = "grid"

    try:
        per_page = int(params.get("per_page") or ALLOWED_PER_PAGE[0])
    except ValueError:
        per_page = ALLOWED_PER_PAGE[0]
    if per_page not in ALLOWED_PER_PAGE:
        per_page = ALLOWED_PER_PAGE[0]

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
        query = query.filter(or_(*[Product.category.ilike(f"%{c}%") for c in selected_categories]))
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
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    if page > total_pages:
        page = total_pages

    products = query.offset((page - 1) * per_page).limit(per_page).all()

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

    start_idx = (page - 1) * per_page + 1 if total_count else 0
    end_idx = min(page * per_page, total_count)

    return templates.TemplateResponse("catalog.html", {
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
        "view": view,
        "per_page": per_page,
        "per_page_options": ALLOWED_PER_PAGE,
        "page": page,
        "total_pages": total_pages,
        "page_items": make_page_items(page, total_pages, params),
        "active_filters": active_filters,
        "reset_url": build_reset_url(view, per_page),
    })


# ============== СТРАНИЦА ТОВАРА ==============
@app.get("/product/{product_id}", response_class=HTMLResponse)
async def product_page(request: Request, product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)
    return templates.TemplateResponse("product.html", {
        "request": request,
        "product": product,
        "product_categories": _parse_list(product.category),
    })


# ============== О НАС ==============
@app.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    return templates.TemplateResponse("about.html", {"request": request})


# ==================================================
# ==============  АДМИНКА: АВТОРИЗАЦИЯ  ============
# ==================================================

@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_form(request: Request):
    if request.session.get("admin"):
        return RedirectResponse(url="/admin/products", status_code=303)
    return templates.TemplateResponse("admin_login.html", {
        "request": request,
        "error": None,
    })


@app.post("/admin/login")
async def admin_login_submit(request: Request, password: str = Form(...)):
    if secrets.compare_digest(password, ADMIN_PASSWORD):
        request.session["admin"] = True
        return RedirectResponse(url="/admin/products", status_code=303)
    return templates.TemplateResponse("admin_login.html", {
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
    return templates.TemplateResponse("admin_products.html", {
        "request": request,
        "products": products,
    })


def _product_form_context(db: Session, product: Product | None):
    return {
        "product": product,
        "product_categories": _parse_list(product.category) if product else [],
        "all_categories": db.query(Category).order_by(Category.name).all(),
        "all_brands": db.query(Brand).order_by(Brand.name).all(),
    }


@app.get("/admin/products/new", response_class=HTMLResponse)
async def admin_product_new(request: Request, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    ctx = _product_form_context(db, None)
    ctx["request"] = request
    return templates.TemplateResponse("admin_product_form.html", ctx)


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
        category=",".join(categories) if categories else None,
        brand=brand.strip() or None,
        price=price,
        volume=volume.strip() or None,
        description=description.strip() or None,
        popular=bool(popular),
        image=image_url,
    )
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
    return templates.TemplateResponse("admin_product_form.html", ctx)


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
    product.category = ",".join(categories) if categories else None
    product.brand = brand.strip() or None
    product.price = price
    product.volume = volume.strip() or None
    product.description = description.strip() or None
    product.popular = bool(popular)

    if remove_image:
        product.image = None
    new_image = _save_upload(image)
    if new_image:
        product.image = new_image

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
        db.delete(product)
        db.commit()
    return RedirectResponse(url="/admin/products", status_code=303)


# ==================================================
# ==============  АДМИНКА: КАТЕГОРИИ  ==============
# ==================================================

@app.get("/admin/categories", response_class=HTMLResponse)
async def admin_categories(request: Request, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    categories = db.query(Category).order_by(Category.name).all()

    counts = {}
    for (cat_str,) in db.query(Product.category).all():
        for c in _parse_list(cat_str):
            counts[c] = counts.get(c, 0) + 1

    return templates.TemplateResponse("admin_categories.html", {
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
        _remove_category_from_all_products(db, category.name)
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

    return templates.TemplateResponse("admin_brands.html", {
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


# ============== СТАРТ: тестовые данные + миграция ==============
@app.on_event("startup")
async def startup():
    db = next(get_db())

    if db.query(Product).count() == 0:
        test_products = [
            Product(name="Гидрофильное масло", category="Очищение,Уход", brand="Avelea", price=1290, popular=True,
                   description="Нежное гидрофильное масло на основе натуральных растительных экстрактов.",
                   volume="150 мл"),
            Product(name="Сыворотка с витамином C", category="Уход", brand="Avelea", price=2450, popular=True,
                   description="Концентрированная сыворотка с 15% стабильным витамином C.",
                   volume="30 мл"),
            Product(name="Увлажняющий крем", category="Уход", brand="Avelea", price=1890, popular=True,
                   description="Лёгкий увлажняющий крем с комплексом из 5 типов гиалуроновой кислоты.",
                   volume="50 мл"),
            Product(name="SPF 50+ тональный", category="Макияж,Уход", brand="Avelea", price=1680, popular=False,
                   description="Тональный крем с высокой солнцезащитой SPF 50+.",
                   volume="40 мл"),
            Product(name="Мицеллярная вода", category="Очищение", brand="Avelea", price=890, popular=False,
                   description="Мягкая мицеллярная вода для бережного очищения.",
                   volume="250 мл"),
            Product(name="Бальзам для губ", category="Уход", brand="Avelea", price=450, popular=True,
                   description="Питательный бальзам для губ с маслом ши и витамином E.",
                   volume="4.5 г"),
        ]
        db.add_all(test_products)
        db.commit()
        print("✅ База данных заполнена тестовыми товарами")

    # Миграция: старые теги -> категории
    migrated = 0
    for p in db.query(Product).all():
        if p.tags:
            cats = _parse_list(p.category)
            for t in _parse_list(p.tags):
                if t not in cats:
                    cats.append(t)
            p.category = ",".join(cats) if cats else None
            p.tags = None
            migrated += 1
    if migrated:
        db.commit()
        print(f"✅ Теги перенесены в категории у {migrated} товаров")

    # Миграция категорий в справочник
    if db.query(Category).count() == 0:
        seen = set()
        for (cat_str,) in db.query(Product.category).all():
            for c in _parse_list(cat_str):
                seen.add(c)
        for c in sorted(seen):
            db.add(Category(name=c))
        if seen:
            db.commit()
            print(f"✅ В справочник категорий мигрировано: {len(seen)}")

    # Миграция брендов
    if db.query(Brand).count() == 0:
        seen = set()
        for (b,) in db.query(Product.brand).all():
            if b:
                seen.add(b)
        for b in sorted(seen):
            db.add(Brand(name=b))
        if seen:
            db.commit()
            print(f"✅ В справочник брендов мигрировано: {len(seen)}")