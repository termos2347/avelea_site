"""Админка: CRUD товаров."""
from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Request, UploadFile,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.data import cache
from app.core.database import get_db
from app.core.deps import require_admin
from app.utils.helpers import (
    make_page_items,
    build_page_url,
    parse_volume,
    resolve_brand_id,
    resolve_categories,
    validate_price,
)
from app.data.models import Product, Brand, Category
from app.services.storage import save_image, delete_image
from app.core.rendering import admin_templates

router = APIRouter(prefix="/admin/products", tags=["admin-products"])

ADMIN_PRODUCTS_PER_PAGE = 50


def _product_form_context(db: Session, product: Product | None):
    """Единый контекст для _product_form.html (и create, и edit)."""
    volume_amount, volume_unit = parse_volume(product.volume if product else None)
    return {
        "product": product,
        "product_categories": [c.name for c in product.categories] if product else [],
        "all_categories": cache.get_categories(),
        "all_brands": cache.get_brands(),
        "volume_amount": volume_amount,
        "volume_unit": volume_unit,
    }


def _apply_image_slot(
    request: Request,
    old_filename: str | None,
    new_file: UploadFile | None,
    remove_flag: str | None,
) -> str | None:
    """Единая логика для одного слота галереи.

    Приоритет: новый файл > удаление > оставить как было.
    Старый файл удаляется, если перестал использоваться.
    """
    new_filename, err = (None, None)
    if new_file is not None and getattr(new_file, "filename", ""):
        new_filename, err = save_image(new_file)
        if err:
            request.session["flash_error"] = err

    if new_filename:
        final = new_filename
    elif remove_flag:
        final = None
    else:
        final = old_filename

    if old_filename and old_filename != final:
        delete_image(old_filename)

    return final


# ============================================================
# Список
# ============================================================

@router.get("", response_class=HTMLResponse)
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

    query = db.query(Product)
    if q:
        query = query.filter(
            Product.name_lower.contains(q.lower(), autoescape=True)
        )
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
            build_page_url(params, page - 1, "/admin/products")
            if page > 1 else None
        ),
        "next_url": (
            build_page_url(params, page + 1, "/admin/products")
            if page < total_pages else None
        ),
        "flash_error": flash_error,
    })


# ============================================================
# Создание
# ============================================================

@router.get("/new", response_class=HTMLResponse)
async def admin_product_new(request: Request, _: bool = Depends(require_admin)):
    return RedirectResponse(url="/admin/products", status_code=303)


@router.post("/new")
async def admin_product_create(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
    name: str = Form(...),
    categories: list[str] = Form([]),
    brand_id: str = Form(None),
    price: int = Form(...),
    volume_amount: str = Form(...),
    volume_unit: str = Form(...),
    description: str = Form(""),
    composition: str = Form(""),
    usage: str = Form(""),
    popular: str = Form(None),
    image_1: UploadFile = File(None),
    image_2: UploadFile = File(None),
    image_3: UploadFile = File(None),
    image_4: UploadFile = File(None),
):
    if (err := validate_price(price)) is not None:
        request.session["flash_error"] = err
        return RedirectResponse(url="/admin/products", status_code=303)

    if not categories and db.query(Category).count() > 0:
        request.session["flash_error"] = (
            "Выберите хотя бы одну категорию — товар не создан."
        )
        return RedirectResponse(url="/admin/products", status_code=303)

    if (not brand_id or not brand_id.strip()) and db.query(Brand).count() > 0:
        request.session["flash_error"] = "Выберите бренд — товар не создан."
        return RedirectResponse(url="/admin/products", status_code=303)

    f1, e1 = save_image(image_1)
    f2, e2 = save_image(image_2)
    f3, e3 = save_image(image_3)
    f4, e4 = save_image(image_4)
    for err in (e1, e2, e3, e4):
        if err:
            request.session["flash_error"] = err
            break

    volume_str = (
        f"{volume_amount.strip()} {volume_unit.strip()}"
        if volume_amount.strip() else None
    )

    product = Product(
        name=name.strip(),
        brand_id=resolve_brand_id(db, brand_id),
        price=price,
        volume=volume_str,
        description=description.strip() or None,
        composition=composition.strip() or None,
        usage=usage.strip() or None,
        popular=bool(popular),
        image=f1,
        image_2=f2,
        image_3=f3,
        image_4=f4,
    )
    product.categories = resolve_categories(db, categories)

    db.add(product)
    db.commit()

    cache.invalidate()

    return RedirectResponse(url="/admin/products", status_code=303)


# ============================================================
# Редактирование
# ============================================================

@router.get("/{product_id}/edit", response_class=HTMLResponse)
async def admin_product_edit(
    request: Request,
    product_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
):
    product = next((p for p in cache.get_products() if p.id == product_id), None)
    if not product:
        raise HTTPException(status_code=404)

    ctx = _product_form_context(db, product)

    if request.headers.get("hx-request") == "true":
        ctx["in_dialog"] = True
        return admin_templates.TemplateResponse(request, "_product_form.html", ctx)

    return admin_templates.TemplateResponse(request, "product_form.html", ctx)


@router.post("/{product_id}/edit")
async def admin_product_update(
    request: Request,
    product_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
    name: str = Form(...),
    categories: list[str] = Form([]),
    brand_id: str = Form(None),
    price: int = Form(...),
    volume_amount: str = Form(...),
    volume_unit: str = Form(...),
    description: str = Form(""),
    composition: str = Form(""),
    usage: str = Form(""),
    popular: str = Form(None),
    image_1: UploadFile = File(None),
    image_2: UploadFile = File(None),
    image_3: UploadFile = File(None),
    image_4: UploadFile = File(None),
    remove_image:   str = Form(None),
    remove_image_2: str = Form(None),
    remove_image_3: str = Form(None),
    remove_image_4: str = Form(None),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404)

    if (err := validate_price(price)) is not None:
        request.session["flash_error"] = err
        return RedirectResponse(url="/admin/products", status_code=303)

    if not categories and db.query(Category).count() > 0:
        request.session["flash_error"] = (
            "Выберите хотя бы одну категорию — изменения не сохранены."
        )
        return RedirectResponse(url="/admin/products", status_code=303)

    if (not brand_id or not brand_id.strip()) and db.query(Brand).count() > 0:
        request.session["flash_error"] = (
            "Выберите бренд — изменения не сохранены."
        )
        return RedirectResponse(url="/admin/products", status_code=303)

    product.name = name.strip()
    product.brand_id = resolve_brand_id(db, brand_id)
    product.price = price
    product.volume = (
        f"{volume_amount.strip()} {volume_unit.strip()}"
        if volume_amount.strip() else None
    )
    product.description = description.strip() or None
    product.composition = composition.strip() or None
    product.usage = usage.strip() or None
    product.popular = bool(popular)

    product.categories = resolve_categories(db, categories)

    product.image = _apply_image_slot(
        request, product.image, image_1, remove_image,
    )
    product.image_2 = _apply_image_slot(
        request, product.image_2, image_2, remove_image_2,
    )
    product.image_3 = _apply_image_slot(
        request, product.image_3, image_3, remove_image_3,
    )
    product.image_4 = _apply_image_slot(
        request, product.image_4, image_4, remove_image_4,
    )

    db.commit()
    cache.invalidate()

    return RedirectResponse(url="/admin/products", status_code=303)


# ============================================================
# Удаление
# ============================================================

@router.post("/{product_id}/delete")
async def admin_product_delete(
    request: Request,
    product_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if product:
        files = [
            product.image, product.image_2,
            product.image_3, product.image_4,
        ]
        db.delete(product)
        db.commit()
        for f in files:
            delete_image(f)
        cache.invalidate()
    return RedirectResponse(url="/admin/products", status_code=303)