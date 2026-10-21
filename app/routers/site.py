"""Публичные страницы: главная, каталог, карточка товара, бренды, о нас.

Все роутеры, кроме about, объявлены `def` (не `async def`). Причина:
внутри синхронный доступ к кэшу (cache.get_products()), который при
холодном кэше дёргает SQLAlchemy → блокирует event loop. FastAPI
автоматически выносит `def`-роутеры в threadpool, event loop остаётся
свободным для других запросов.

about — чистый шаблон без I/O, оставлен `async def`.
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.data import cache
from app.utils.helpers import (
    build_filter_url,
    build_page_url,
    build_reset_url,
    make_page_items,
)
from app.core.rendering import site_templates

router = APIRouter(tags=["site"])

PER_PAGE = 12


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    products = [p for p in cache.get_products() if p.is_active]
    categories = cache.get_categories()

    popular = [p for p in products if p.popular][:6]

    return site_templates.TemplateResponse(request, "index.html", {
        "popular": popular,
        "categories": categories,
    })


@router.get("/catalog", response_class=HTMLResponse)
def catalog(request: Request):
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

    # Только активные товары видны клиентам.
    all_products = [p for p in cache.get_products() if p.is_active]
    all_categories = cache.get_categories()
    all_brands_used = cache.get_brand_names()

    filtered = []
    for p in all_products:
        if q:
            # Ищем по p.name.lower(), а не по p.name_lower.
            # name_lower — денормализованная колонка для индексируемого
            # SQL-поиска (админка). На сайте товаров немного, кэш уже
            # в памяти — p.name надёжнее (источник правды, .lower()
            # в Python корректно работает с кириллицей).
            if q not in (p.name or "").lower():
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

    total_count = len(filtered)
    total_pages = max(1, (total_count + PER_PAGE - 1) // PER_PAGE)
    if page > total_pages:
        page = total_pages

    start = (page - 1) * PER_PAGE
    end = start + PER_PAGE
    products = filtered[start:end]

    category_names = [c.name for c in all_categories]

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


@router.get("/product/{slug_or_id}")
def product_page(request: Request, slug_or_id: str):
    all_products = cache.get_products()

    # 1. Ищем по slug.
    product = next((p for p in all_products if p.slug == slug_or_id), None)

    # 2. Если не нашли и это число — ищем по id.
    #    Скрытые товары НЕ редиректим на slug — иначе 301 утекает
    #    существование скрытого товара (301 → 404 = «товар был»).
    if product is None and slug_or_id.isdigit():
        product = next(
            (p for p in all_products if p.id == int(slug_or_id)),
            None,
        )
        if product and product.is_active and product.slug:
            return RedirectResponse(
                url=f"/product/{product.slug}",
                status_code=301,
            )

    # 3. Скрытые товары на публичной стороне → 404.
    if not product or not product.is_active:
        raise HTTPException(status_code=404)

    cat_names = {c.name for c in product.categories}
    similar = [
        p for p in all_products
        if p.id != product.id
        and p.is_active
        and ({c.name for c in p.categories} & cat_names)
    ][:6]

    return site_templates.TemplateResponse(request, "product.html", {
        "product": product,
        "product_categories": [c.name for c in product.categories],
        "similar": similar,
    })


@router.get("/brands", response_class=HTMLResponse)
def brands_page(request: Request):
    """Страница всех брендов с алфавитным указателем (только A-Z, 0-9)."""
    brands = cache.get_brands()

    # Простая транслитерация первой буквы на случай кириллицы
    cyr_to_lat = {
        'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'E',
        'Ж': 'Z', 'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M',
        'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U',
        'Ф': 'F', 'Х': 'H', 'Ц': 'T', 'Ч': 'C', 'Ш': 'S', 'Щ': 'S', 'Ъ': 'Z',
        'Ы': 'Y', 'Ь': 'Z', 'Э': 'E', 'Ю': 'Y', 'Я': 'Y'
    }

    grouped = {}
    for brand in brands:
        if not brand.name:
            continue

        first_char = brand.name.strip()[0].upper()

        # Определяем ключ группы
        if first_char.isdigit():
            key = "0 - 9"
        elif first_char in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            key = first_char
        else:
            # Пробуем транслитерировать
            lat_char = cyr_to_lat.get(first_char)
            if lat_char and lat_char in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                key = lat_char
            else:
                # Всё остальное (символы и т.д.) кидаем в цифры
                key = "0 - 9"

        if key not in grouped:
            grouped[key] = []
        grouped[key].append(brand)

    # Сортируем: сначала цифры, потом буквы по алфавиту
    def sort_key(k):
        if k == "0 - 9":
            return "0"
        return k

    sorted_grouped = sorted(grouped.items(), key=lambda x: sort_key(x[0]))

    # Алфавит только английский + цифры
    alphabet = ["0 - 9"] + list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    existing_keys = {k for k, v in sorted_grouped}

    return site_templates.TemplateResponse(request, "brands.html", {
        "grouped_brands": sorted_grouped,
        "existing_keys": existing_keys,
        "alphabet": alphabet,
    })


@router.get("/about", response_class=HTMLResponse)
def about(request: Request):
    return site_templates.TemplateResponse(request, "about.html")