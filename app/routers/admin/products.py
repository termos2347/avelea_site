"""Админка: CRUD товаров.

Все роутеры объявлены `def` (не `async def`), потому что внутри
синхронные db.query(...) и save_media(...). FastAPI выносит `def`-роутеры
в threadpool, event loop не блокируется.
"""
import logging

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Request, UploadFile,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.exc import SQLAlchemyError
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
from app.data.models import Product, ProductVariant, Brand, Category
from app.services.storage import save_media, delete_media
from app.core.rendering import admin_templates

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/products", tags=["admin-products"])

ADMIN_PRODUCTS_PER_PAGE = 50
MAX_VARIANTS = 10

_COMMIT_ERROR_MSG = (
    "Не удалось сохранить — временная ошибка базы данных. "
    "Попробуйте ещё раз через минуту."
)


def _product_form_context(db: Session, product: Product | None):
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
    had_upload = new_file is not None and getattr(new_file, "filename", "")

    if had_upload:
        new_filename, err = save_media(new_file)
        if err:
            request.session["flash_error"] = err
            return old_filename
        if new_filename:
            if old_filename and old_filename != new_filename:
                delete_media(old_filename)
            return new_filename

    if remove_flag:
        if old_filename:
            delete_media(old_filename)
        return None

    return old_filename


def _save_variants(
    product: Product,
    amounts: list[str],
    units: list[str],
    prices: list[str],
) -> list[str]:
    """Пересобирает варианты товара из данных формы.

    Возвращает список ошибок — невалидные строки, которые были
    выкинуты (админ должен об этом узнать, а не молча потерять
    вариант после сохранения).
    """
    product.variants.clear()

    rows = []
    dropped: list[str] = []
    for i, (amount, unit, price_str) in enumerate(zip(amounts, units, prices)):
        if i >= MAX_VARIANTS:
            dropped.append(f"строка {i+1}: превышен лимит {MAX_VARIANTS} вариантов")
            break
        amount = (amount or "").strip()
        unit = (unit or "мл").strip()
        price_str = (price_str or "").strip()

        if not amount and not price_str:
            continue

        if not amount or not price_str:
            dropped.append(f"строка {i+1}: не заполнены объём или цена")
            continue
        try:
            price = int(price_str)
        except ValueError:
            dropped.append(f"строка {i+1}: цена «{price_str}» — не число")
            continue
        if price < 0:
            dropped.append(f"строка {i+1}: цена не может быть отрицательной")
            continue

        rows.append(ProductVariant(
            volume_amount=amount,
            volume_unit=unit,
            price=price,
            sort_order=i,
        ))

    product.variants = rows
    if rows:
        product.price = min(v.price for v in rows)
        product.volume = None

    return dropped


# ============================================================
# Список
# ============================================================

@router.get("", response_class=HTMLResponse)
def admin_products(
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
def admin_product_new(request: Request, _: bool = Depends(require_admin)):
    return RedirectResponse(url="/admin/products", status_code=303)


@router.post("/new")
def admin_product_create(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
    name: str = Form(...),
    categories: list[str] = Form([]),
    brand_id: str = Form(None),
    price: int = Form(...),
    volume_amount: str = Form(""),
    volume_unit: str = Form("мл"),
    description: str = Form(""),
    composition: str = Form(""),
    usage: str = Form(""),
    popular: str = Form(None),
    is_active: str = Form(None),
    image_1: UploadFile = File(None),
    image_2: UploadFile = File(None),
    image_3: UploadFile = File(None),
    image_4: UploadFile = File(None),
    variant_volume_amount: list[str] = Form([]),
    variant_volume_unit:   list[str] = Form([]),
    variant_price:         list[str] = Form([]),
):
    if (err := validate_price(price)) is not None:
        request.session["flash_error"] = err
        return RedirectResponse(url="/admin/products", status_code=303)

    if not categories and db.query(Category).count() > 0:
        request.session["flash_error"] = "Выберите хотя бы одну категорию — товар не создан."
        return RedirectResponse(url="/admin/products", status_code=303)

    if (not brand_id or not brand_id.strip()) and db.query(Brand).count() > 0:
        request.session["flash_error"] = "Выберите бренд — товар не создан."
        return RedirectResponse(url="/admin/products", status_code=303)

    f1, e1 = save_media(image_1)
    f2, e2 = save_media(image_2)
    f3, e3 = save_media(image_3)
    f4, e4 = save_media(image_4)
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
        is_active=bool(is_active),
        image=f1, image_2=f2, image_3=f3, image_4=f4,
    )
    product.categories = resolve_categories(db, categories)

    dropped = _save_variants(
        product, variant_volume_amount, variant_volume_unit, variant_price,
    )
    if dropped:
        request.session["flash_error"] = (
            "Варианты пропущены: " + "; ".join(dropped)
        )

    try:
        db.add(product)
        db.commit()
        cache.invalidate()
    except SQLAlchemyError as exc:
        db.rollback()
        log.exception("product create failed: %s", exc)
        request.session["flash_error"] = (
            "Не удалось создать товар — временная ошибка БД. "
            "Попробуйте ещё раз."
        )
        return RedirectResponse(url="/admin/products", status_code=303)

    return RedirectResponse(url="/admin/products", status_code=303)


# ============================================================
# Редактирование
# ============================================================

@router.get("/{product_id}/edit", response_class=HTMLResponse)
def admin_product_edit(
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
def admin_product_update(
    request: Request,
    product_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
    name: str = Form(...),
    categories: list[str] = Form([]),
    brand_id: str = Form(None),
    price: int = Form(...),
    volume_amount: str = Form(""),
    volume_unit: str = Form("мл"),
    description: str = Form(""),
    composition: str = Form(""),
    usage: str = Form(""),
    popular: str = Form(None),
    is_active: str = Form(None),
    image_1: UploadFile = File(None),
    image_2: UploadFile = File(None),
    image_3: UploadFile = File(None),
    image_4: UploadFile = File(None),
    remove_image:   str = Form(None),
    remove_image_2: str = Form(None),
    remove_image_3: str = Form(None),
    remove_image_4: str = Form(None),
    variant_volume_amount: list[str] = Form([]),
    variant_volume_unit:   list[str] = Form([]),
    variant_price:         list[str] = Form([]),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404)

    if (err := validate_price(price)) is not None:
        request.session["flash_error"] = err
        return RedirectResponse(url="/admin/products", status_code=303)

    if not categories and db.query(Category).count() > 0:
        request.session["flash_error"] = "Выберите хотя бы одну категорию — изменения не сохранены."
        return RedirectResponse(url="/admin/products", status_code=303)

    if (not brand_id or not brand_id.strip()) and db.query(Brand).count() > 0:
        request.session["flash_error"] = "Выберите бренд — изменения не сохранены."
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
    product.is_active = bool(is_active)

    product.categories = resolve_categories(db, categories)

    product.image = _apply_image_slot(request, product.image, image_1, remove_image)
    product.image_2 = _apply_image_slot(request, product.image_2, image_2, remove_image_2)
    product.image_3 = _apply_image_slot(request, product.image_3, image_3, remove_image_3)
    product.image_4 = _apply_image_slot(request, product.image_4, image_4, remove_image_4)

    dropped = _save_variants(
        product, variant_volume_amount, variant_volume_unit, variant_price,
    )
    if dropped:
        request.session["flash_error"] = (
            "Варианты пропущены: " + "; ".join(dropped)
        )

    try:
        db.commit()
        cache.invalidate()
    except SQLAlchemyError as exc:
        db.rollback()
        log.exception("product update failed: %s", exc)
        request.session["flash_error"] = (
            "Не удалось сохранить изменения — временная ошибка БД. "
            "Попробуйте ещё раз."
        )
        return RedirectResponse(
            url=f"/admin/products/{product.id}/edit",
            status_code=303,
        )

    return RedirectResponse(url="/admin/products", status_code=303)


# ============================================================
# Удаление
# ============================================================

@router.post("/{product_id}/delete")
def admin_product_delete(
    request: Request,
    product_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if product:
        files = [product.image, product.image_2, product.image_3, product.image_4]
        try:
            db.delete(product)
            db.commit()
            for f in files:
                delete_media(f)
            cache.invalidate()
        except SQLAlchemyError as exc:
            db.rollback()
            log.exception("product delete failed: %s", exc)
            request.session["flash_error"] = _COMMIT_ERROR_MSG
    return RedirectResponse(url="/admin/products", status_code=303)