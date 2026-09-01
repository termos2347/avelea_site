from fastapi import FastAPI, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import json
import os

from app.database import engine, get_db, Base
from app.models import Product

# Создаём таблицы
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Avelea Shop")

# Шаблоны
templates = Jinja2Templates(directory="app/templates")

# ============== Хелпер для корзины ==============
def get_cart_from_request(request: Request):
    cart = request.cookies.get("cart")
    if cart:
        try:
            return json.loads(cart)
        except:
            return {}
    return {}

def set_cart_in_response(response, cart):
    response.set_cookie(key="cart", value=json.dumps(cart))

# ============== СТРАНИЦА "О НАС" ==============
@app.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    return templates.TemplateResponse("about.html", {
        "request": request,
        "cart": get_cart_from_request(request)
    })

# ============== ГЛАВНАЯ ==============
@app.get("/", response_class=HTMLResponse)
async def index(request: Request, db: Session = Depends(get_db)):
    popular = db.query(Product).filter(Product.popular == True).limit(6).all()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "popular": popular,
        "cart": get_cart_from_request(request)
    })

# ============== КАТАЛОГ С ФИЛЬТРАМИ ==============
@app.get("/catalog", response_class=HTMLResponse)
async def catalog(
    request: Request,
    category: str = None,
    brand: str = None,
    db: Session = Depends(get_db)
):
    query = db.query(Product)
    if category:
        query = query.filter(Product.category == category)
    if brand:
        query = query.filter(Product.brand == brand)
    
    products = query.all()
    
    categories = db.query(Product.category).distinct().all()
    brands = db.query(Product.brand).distinct().all()
    
    return templates.TemplateResponse("catalog.html", {
        "request": request,
        "products": products,
        "categories": [c[0] for c in categories if c[0]],
        "brands": [b[0] for b in brands if b[0]],
        "selected_category": category,
        "selected_brand": brand,
        "cart": get_cart_from_request(request)
    })

# ============== ДОБАВЛЕНИЕ В КОРЗИНУ ==============
@app.post("/add_to_cart/{product_id}")
async def add_to_cart(request: Request, product_id: int):
    cart = get_cart_from_request(request)
    cart[str(product_id)] = cart.get(str(product_id), 0) + 1
    response = RedirectResponse(url="/catalog", status_code=303)
    set_cart_in_response(response, cart)
    return response

# ============== КОРЗИНА ==============
@app.get("/cart", response_class=HTMLResponse)
async def cart_page(request: Request, db: Session = Depends(get_db)):
    cart = get_cart_from_request(request)
    items = []
    total = 0
    for pid, qty in cart.items():
        product = db.query(Product).filter(Product.id == int(pid)).first()
        if product:
            items.append({"product": product, "qty": qty})
            total += product.price * qty
    return templates.TemplateResponse("cart.html", {
        "request": request,
        "items": items,
        "total": total,
        "cart": cart
    })

# ============== ОБНОВЛЕНИЕ КОЛИЧЕСТВА ==============
@app.post("/update_cart")
async def update_cart(
    request: Request,
    product_id: int = Form(...),
    quantity: int = Form(...)
):
    cart = get_cart_from_request(request)
    if quantity <= 0:
        cart.pop(str(product_id), None)
    else:
        cart[str(product_id)] = quantity
    response = RedirectResponse(url="/cart", status_code=303)
    set_cart_in_response(response, cart)
    return response

# ============== СТРАНИЦА ТОВАРА ==============
@app.get("/product/{product_id}", response_class=HTMLResponse)
async def product_page(request: Request, product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)
    return templates.TemplateResponse("product.html", {
        "request": request,
        "product": product,
        "cart": get_cart_from_request(request)
    })

# ============== ЗАПОЛНЕНИЕ ТЕСТОВЫМИ ДАННЫМИ ==============
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