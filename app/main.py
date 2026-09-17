from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.exceptions import RequestValidationError
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session
from urllib.parse import urlencode
import os

from app.database import engine, get_db, Base
from app.models import Product

os.makedirs("instance", exist_ok=True)
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Avelea Shop")
templates = Jinja2Templates(directory="app/templates")


# ============== ХЕЛПЕР ДЛЯ URL БЕЗ ОДНОГО ФИЛЬТРА ==============
def build_filter_url(params, remove_key: str, remove_value: str = None) -> str:
    """Собирает /catalog?... без указанного параметра (или одного из его значений)."""
    pairs = []
    for k in params.keys():
        for v in params.getlist(k):
            if k == remove_key and (remove_value is None or v == remove_value):
                continue
            pairs.append((k, v))
    qs = urlencode(pairs)
    return "/catalog" + ("?" + qs if qs else "")


# ============== ГЛОБАЛЬНЫЙ 404 ==============
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


# ============== КАТАЛОГ С ФИЛЬТРАМИ ==============
@app.get("/catalog", response_class=HTMLResponse)
async def catalog(request: Request, db: Session = Depends(get_db)):
    params = request.query_params

    q = (params.get("q") or "").strip()
    selected_categories = params.getlist("category")
    selected_brands = params.getlist("brand")
    selected_tags = params.getlist("tag")
    price_min = params.get("price_min") or ""
    price_max = params.get("price_max") or ""
    sort = params.get("sort") or ""

    query = db.query(Product)

    if q:
        query = query.filter(Product.name.ilike(f"%{q}%"))
    if selected_categories:
        query = query.filter(Product.category.in_(selected_categories))
    if selected_brands:
        query = query.filter(Product.brand.in_(selected_brands))
    if selected_tags:
        query = query.filter(or_(*[Product.tags.ilike(f"%{t}%") for t in selected_tags]))
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

    products = query.all()

    # Опции для фильтров — из БД
    all_categories = [c[0] for c in db.query(Product.category).distinct().all() if c[0]]
    all_brands = [b[0] for b in db.query(Product.brand).distinct().all() if b[0]]

    tags_set = set()
    for (tags_str,) in db.query(Product.tags).all():
        if tags_str:
            for t in tags_str.split(","):
                t = t.strip()
                if t:
                    tags_set.add(t)
    all_tags = sorted(tags_set)

    # Чипсы активных фильтров
    active_filters = []
    if q:
        active_filters.append({"label": f"Поиск: {q}", "remove_url": build_filter_url(params, "q")})
    for c in selected_categories:
        active_filters.append({"label": c, "remove_url": build_filter_url(params, "category", c)})
    for b in selected_brands:
        active_filters.append({"label": b, "remove_url": build_filter_url(params, "brand", b)})
    for t in selected_tags:
        active_filters.append({"label": t, "remove_url": build_filter_url(params, "tag", t)})
    if price_min:
        active_filters.append({"label": f"от {price_min} ₽", "remove_url": build_filter_url(params, "price_min")})
    if price_max:
        active_filters.append({"label": f"до {price_max} ₽", "remove_url": build_filter_url(params, "price_max")})

    return templates.TemplateResponse("catalog.html", {
        "request": request,
        "products": products,
        "total_count": len(products),
        "categories": all_categories,
        "brands": all_brands,
        "all_tags": all_tags,
        "selected_categories": selected_categories,
        "selected_brands": selected_brands,
        "selected_tags": selected_tags,
        "price_min": price_min,
        "price_max": price_max,
        "q": q,
        "sort": sort,
        "active_filters": active_filters,
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
    })


# ============== СТРАНИЦА "О НАС" ==============
@app.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    return templates.TemplateResponse("about.html", {"request": request})


# ============== ТЕСТОВЫЕ ДАННЫЕ ==============
@app.on_event("startup")
async def startup():
    db = next(get_db())
    if db.query(Product).count() == 0:
        test_products = [
            Product(name="Гидрофильное масло", category="Очищение", brand="Avelea", price=1290, popular=True,
                   description="Нежное гидрофильное масло на основе натуральных растительных экстрактов.",
                   volume="150 мл", tags="очищение,для всех типов кожи"),
            Product(name="Сыворотка с витамином C", category="Уход", brand="Avelea", price=2450, popular=True,
                   description="Концентрированная сыворотка с 15% стабильным витамином C.",
                   volume="30 мл", tags="осветление,антивозрастной"),
            Product(name="Увлажняющий крем", category="Уход", brand="Avelea", price=1890, popular=True,
                   description="Лёгкий увлажняющий крем с комплексом из 5 типов гиалуроновой кислоты.",
                   volume="50 мл", tags="увлажнение,для чувствительной кожи"),
            Product(name="SPF 50+ тональный", category="Макияж", brand="Avelea", price=1680, popular=False,
                   description="Тональный крем с высокой солнцезащитой SPF 50+.",
                   volume="40 мл", tags="SPF,защита"),
            Product(name="Мицеллярная вода", category="Очищение", brand="Avelea", price=890, popular=False,
                   description="Мягкая мицеллярная вода для бережного очищения.",
                   volume="250 мл", tags="очищение,для чувствительной кожи"),
            Product(name="Бальзам для губ", category="Уход", brand="Avelea", price=450, popular=True,
                   description="Питательный бальзам для губ с маслом ши и витамином E.",
                   volume="4.5 г", tags="питание,восстановление"),
        ]
        db.add_all(test_products)
        db.commit()
        print("✅ База данных заполнена тестовыми товарами")