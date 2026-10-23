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
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.data import cache
from app.core.database import get_db
from app.core.security import require_admin
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
MAX_NAME_LEN = 200
MAX_TEXT_LEN = 10000

_COMMIT_ERROR_MSG = (
    "Не удалось сохранить — временная ошибка базы данных. "
    "Попробуйте ещё раз через минуту."
)
_DUPLICATE_NAME_MSG = (
    "Товар с таким названием уже существует. "
    "Попробуйте изменить название."
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
        "current_slug": product.slug if product else "",
    }


def _append_flash(request: Request, msg: str) -> None:
    existing = request.session.get("flash_error") or ""
    request.session["flash_error"] = (
        f"{existing}; {msg}" if existing else msg
    )


def _parse_price(request: Request, raw: str, action: str) -> int | None:
    raw = (raw or "").strip()
    if not raw:
        request.session["flash_error"] = f"Укажите цену — {action}."
        return None
    try:
        return int(raw)
    except ValueError:
        request.session["flash_error"] = f"Цена «{raw}» — не число, {action}."
        return None


def _apply_image_slot(
    old_filename: str | None,
    new_file: UploadFile | None,
    remove_flag: str | None,
    files_to_delete: list[str],
    files_to_rollback: list[str],
    errors: list[str],
) -> str | None:
    had_upload = new_file is not None and getattr(new_file, "filename", "")

    if had_upload:
        new_filename, err = save_media(new_file)
        if err:
            errors.append(err)
            return old_filename
        if new_filename:
            files_to_rollback.append(new_filename)
            if old_filename and old_filename != new_filename:
                files_to_delete.append(old_filename)
            return new_filename

    if remove_flag:
        if old_filename:
            files_to_delete.append(old_filename)
        return None

    return old_filename


def _save_variants(
    product: Product,
    amounts: list[str],
    units: list[str],
    prices: list[str],
) -> list[str]:
    had_variants = bool(product.variants)
    product.variants.clear()

    rows = []
    warnings: list[str] = []
    for i, (amount, unit, price_str) in enumerate(zip(amounts, units, prices)):
        if i >= MAX_VARIANTS:
            warnings.append(
                f"строка {i+1}: превышен лимит {MAX_VARIANTS} вариантов"
            )
            break
        amount = (amount or "").strip()
        unit = (unit or "мл").strip()
        price_str = (price_str or "").strip()

        if not amount and not price_str:
            continue

        if not amount or not price_str:
            warnings.append(f"строка {i+1}: не заполнены объём или цена")
            continue
        try:
            price = int(price_str)
        except ValueError:
            warnings.append(f"строка {i+1}: цена «{price_str}» — не число")
            continue
        if price < 0:
            warnings.append(f"строка {i+1}: цена не может быть отрицательной")
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
    elif had_variants:
        warnings.append(
            f"все варианты удалены — используется базовая цена {product.price} ₽"
        )

    return warnings


# ============================================================
# Общая логика списка
# ============================================================

def _build_products_context(request: Request, db: Session) -> dict:
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

    return {
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
    }


# ============================================================
# Список и подгрузка
# ============================================================

@router.get("", response_class=HTMLResponse)
def admin_products(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
):
    ctx = _build_products_context(request, db)
    ctx["flash_error"] = request.session.pop("flash_error", None)
    return admin_templates.TemplateResponse(request, "products.html", ctx)


@router.get("/more", response_class=HTMLResponse)
def admin_products_more(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
):
    """Фрагмент для кнопки «Показать ещё»."""
    ctx = _build_products_context(request, db)
    return admin_templates.TemplateResponse(request, "_product_rows.html", ctx)


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
    name: str = Form(..., max_length=MAX_NAME_LEN),
    slug: str = Form(""),
    categories: list[str] = Form([]),
    brand_id: str = Form(None),
    price: str = Form(""),
    volume_amount: str = Form(""),
    volume_unit: str = Form("мл"),
    description: str = Form("", max_length=MAX_TEXT_LEN),
    composition: str = Form("", max_length=MAX_TEXT_LEN),
    usage: str = Form("", max_length=MAX_TEXT_LEN),
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
    price_int = _parse_price(request, price, "товар не создан")
    if price_int is None:
        return RedirectResponse(url="/admin/products", status_code=303)

    if (err := validate_price(price_int)) is not None:
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

    f1, e1 = save_media(image_1)
    f2, e2 = save_media(image_2)
    f3, e3 = save_media(image_3)
    f4, e4 = save_media(image_4)

    saved_files = [f for f in (f1, f2, f3, f4) if f]
    media_errors = [e for e in (e1, e2, e3, e4) if e]
    if media_errors:
        _append_flash(request, "; ".join(media_errors))

    volume_str = (
        f"{volume_amount.strip()} {volume_unit.strip()}"
        if volume_amount.strip() else None
    )

    product = Product(
        name=name.strip(),
        brand_id=resolve_brand_id(db, brand_id),
        price=price_int,
        volume=volume_str,
        description=description.strip() or None,
        composition=composition.strip() or None,
        usage=usage.strip() or None,
        popular=bool(popular),
        is_active=bool(is_active),
        image=f1, image_2=f2, image_3=f3, image_4=f4,
    )
    product.categories = resolve_categories(db, categories)

    warnings = _save_variants(
        product, variant_volume_amount, variant_volume_unit, variant_price,
    )
    if warnings:
        _append_flash(request, "Варианты: " + "; ".join(warnings))

    try:
        db.add(product)
        db.commit()
        cache.invalidate()
    except IntegrityError:
        db.rollback()
        for f in saved_files:
            delete_media(f)
        request.session["flash_error"] = _DUPLICATE_NAME_MSG
        return RedirectResponse(url="/admin/products", status_code=303)
    except SQLAlchemyError as exc:
        db.rollback()
        for f in saved_files:
            delete_media(f)
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
    ctx["flash_error"] = request.session.pop("flash_error", None)

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
    name: str = Form(..., max_length=MAX_NAME_LEN),
    slug: str = Form(""),
    categories: list[str] = Form([]),
    brand_id: str = Form(None),
    price: str = Form(""),
    volume_amount: str = Form(""),
    volume_unit: str = Form("мл"),
    description: str = Form("", max_length=MAX_TEXT_LEN),
    composition: str = Form("", max_length=MAX_TEXT_LEN),
    usage: str = Form("", max_length=MAX_TEXT_LEN),
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

    edit_url = f"/admin/products/{product_id}/edit"

    price_int = _parse_price(request, price, "изменения не сохранены")
    if price_int is None:
        return RedirectResponse(url=edit_url, status_code=303)

    if (err := validate_price(price_int)) is not None:
        request.session["flash_error"] = err
        return RedirectResponse(url=edit_url, status_code=303)

    if not categories and db.query(Category).count() > 0:
        request.session["flash_error"] = (
            "Выберите хотя бы одну категорию — изменения не сохранены."
        )
        return RedirectResponse(url=edit_url, status_code=303)

    if (not brand_id or not brand_id.strip()) and db.query(Brand).count() > 0:
        request.session["flash_error"] = (
            "Выберите бренд — изменения не сохранены."
        )
        return RedirectResponse(url=edit_url, status_code=303)

    product.name = name.strip()
    product.brand_id = resolve_brand_id(db, brand_id)
    product.price = price_int
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

    files_to_delete:   list[str] = []
    files_to_rollback: list[str] = []
    media_errors:      list[str] = []

    product.image   = _apply_image_slot(
        product.image,   image_1, remove_image,
        files_to_delete, files_to_rollback, media_errors,
    )
    product.image_2 = _apply_image_slot(
        product.image_2, image_2, remove_image_2,
        files_to_delete, files_to_rollback, media_errors,
    )
    product.image_3 = _apply_image_slot(
        product.image_3, image_3, remove_image_3,
        files_to_delete, files_to_rollback, media_errors,
    )
    product.image_4 = _apply_image_slot(
        product.image_4, image_4, remove_image_4,
        files_to_delete, files_to_rollback, media_errors,
    )

    if media_errors:
        _append_flash(request, "; ".join(media_errors))

    warnings = _save_variants(
        product, variant_volume_amount, variant_volume_unit, variant_price,
    )
    if warnings:
        _append_flash(request, "Варианты: " + "; ".join(warnings))

    try:
        db.commit()
        cache.invalidate()
    except IntegrityError:
        db.rollback()
        for f in files_to_rollback:
            delete_media(f)
        request.session["flash_error"] = _DUPLICATE_NAME_MSG
        return RedirectResponse(url=edit_url, status_code=303)
    except SQLAlchemyError as exc:
        db.rollback()
        for f in files_to_rollback:
            delete_media(f)
        log.exception("product update failed: %s", exc)
        request.session["flash_error"] = (
            "Не удалось сохранить изменения — временная ошибка БД. "
            "Попробуйте ещё раз."
        )
        return RedirectResponse(url=edit_url, status_code=303)

    for f in files_to_delete:
        delete_media(f)

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