"""Публичные страницы: главная, каталог, карточка товара, о нас."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.data import cache
from app.utils.helpers import (
    build_filter_url,
    build_page_url,
    build_reset_url,
    make_page_items,
)
from app.core.rendering import site_templates

router = APIRouter(tags=["site"])

# Сколько товаров показывать на одной странице каталога.
PER_PAGE = 12


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    products = cache.get_products()
    categories = cache.get_categories()

    popular = [p for p in products if p.popular][:6]

    return site_templates.TemplateResponse(request, "index.html", {
        "popular": popular,
        "categories": categories,
    })


@router.get("/catalog", response_class=HTMLResponse)
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

    category_names = [c.name for c in all_categories]

    # ---------- Чипы активных фильтров ----------
    active_filters = []
    if q:
        active_filters.append({
            "label": f"Поиск: {params.get('q')}",
            "remove_url": build_filter_url(params, "q"),
        })
    for c in selected_categories:
        active_filters.append({
            "label": c,
            "remove_url": build_filter_url(params, "category", c),
        })
    for b in selected_brands:
        active_filters.append({
            "label": b,
            "remove_url": build_filter_url(params, "brand", b),
        })
    if price_min:
        active_filters.append({
            "label": f"от {price_min} ₽",
            "remove_url": build_filter_url(params, "price_min"),
        })
    if price_max:
        active_filters.append({
            "label": f"до {price_max} ₽",
            "remove_url": build_filter_url(params, "price_max"),
        })

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


@router.get("/product/{product_id}", response_class=HTMLResponse)
async def product_page(request: Request, product_id: int):
    all_products = cache.get_products()

    product = next((p for p in all_products if p.id == product_id), None)
    if not product:
        return site_templates.TemplateResponse(
            request, "404.html", status_code=404,
        )

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


@router.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    return site_templates.TemplateResponse(request, "about.html")