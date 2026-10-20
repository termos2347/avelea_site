"""Админка: бренды и категории."""
import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.data import cache
from app.core.database import get_db
from app.core.security import require_admin
from app.data.models import Product, Brand, Category, product_categories
from app.core.rendering import admin_templates

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin-catalog"])


_COMMIT_ERROR_MSG = (
    "Не удалось сохранить — временная ошибка базы данных. "
    "Попробуйте ещё раз через минуту."
)


# ============================================================
# Категории
# ============================================================

@router.get("/categories", response_class=HTMLResponse)
def admin_categories(
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


@router.post("/categories/new")
def admin_category_create(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
    name: str = Form(...),
):
    name = name.strip()
    if not name:
        return RedirectResponse(url="/admin/categories", status_code=303)

    exists = db.query(Category).filter(Category.name == name).first()
    if exists:
        request.session["flash_error"] = f"Категория «{name}» уже существует."
        return RedirectResponse(url="/admin/categories", status_code=303)

    try:
        db.add(Category(name=name))
        db.commit()
        cache.invalidate()
    except IntegrityError:
        db.rollback()
        request.session["flash_error"] = f"Категория «{name}» уже существует."
    except SQLAlchemyError as exc:
        db.rollback()
        log.exception("category create failed: %s", exc)
        request.session["flash_error"] = _COMMIT_ERROR_MSG

    return RedirectResponse(url="/admin/categories", status_code=303)


@router.post("/categories/{category_id}/edit")
def admin_category_edit(
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
    if not name or name == category.name:
        return RedirectResponse(url="/admin/categories", status_code=303)

    exists = (
        db.query(Category)
          .filter(Category.name == name, Category.id != category_id)
          .first()
    )
    if exists:
        request.session["flash_error"] = f"Категория «{name}» уже существует."
        return RedirectResponse(url="/admin/categories", status_code=303)

    try:
        category.name = name
        db.commit()
        cache.invalidate()
    except IntegrityError:
        db.rollback()
        request.session["flash_error"] = f"Категория «{name}» уже существует."
    except SQLAlchemyError as exc:
        db.rollback()
        log.exception("category edit failed: %s", exc)
        request.session["flash_error"] = _COMMIT_ERROR_MSG

    return RedirectResponse(url="/admin/categories", status_code=303)


@router.post("/categories/{category_id}/delete")
def admin_category_delete(
    request: Request,
    category_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
):
    category = db.query(Category).filter(Category.id == category_id).first()
    if category:
        try:
            category.products.clear()
            db.delete(category)
            db.commit()
            cache.invalidate()
        except SQLAlchemyError as exc:
            db.rollback()
            log.exception("category delete failed: %s", exc)
            request.session["flash_error"] = _COMMIT_ERROR_MSG

    return RedirectResponse(url="/admin/categories", status_code=303)


# ============================================================
# Бренды
# ============================================================

@router.get("/brands", response_class=HTMLResponse)
def admin_brands(
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


@router.post("/brands/new")
def admin_brand_create(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
    name: str = Form(...),
    description: str = Form(""),
):
    name = name.strip()
    desc = (description or "").strip() or None
    if not name:
        return RedirectResponse(url="/admin/brands", status_code=303)

    exists = db.query(Brand).filter(Brand.name == name).first()
    if exists:
        request.session["flash_error"] = f"Бренд «{name}» уже существует."
        return RedirectResponse(url="/admin/brands", status_code=303)

    try:
        db.add(Brand(name=name, description=desc))
        db.commit()
        cache.invalidate()
    except IntegrityError:
        db.rollback()
        request.session["flash_error"] = f"Бренд «{name}» уже существует."
    except SQLAlchemyError as exc:
        db.rollback()
        log.exception("brand create failed: %s", exc)
        request.session["flash_error"] = _COMMIT_ERROR_MSG

    return RedirectResponse(url="/admin/brands", status_code=303)


@router.post("/brands/{brand_id}/edit")
def admin_brand_edit(
    request: Request,
    brand_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
    name: str = Form(...),
    description: str = Form(""),
):
    brand = db.query(Brand).filter(Brand.id == brand_id).first()
    if not brand:
        raise HTTPException(status_code=404)

    name = name.strip()
    desc = (description or "").strip() or None

    changed = False

    if name and name != brand.name:
        exists = (
            db.query(Brand)
              .filter(Brand.name == name, Brand.id != brand_id)
              .first()
        )
        if exists:
            request.session["flash_error"] = f"Бренд «{name}» уже существует."
            return RedirectResponse(url="/admin/brands", status_code=303)
        brand.name = name
        changed = True

    if brand.description != desc:
        brand.description = desc
        changed = True

    if changed:
        try:
            db.commit()
            cache.invalidate()
        except IntegrityError:
            db.rollback()
            request.session["flash_error"] = f"Бренд «{name}» уже существует."
        except SQLAlchemyError as exc:
            db.rollback()
            log.exception("brand edit failed: %s", exc)
            request.session["flash_error"] = _COMMIT_ERROR_MSG

    return RedirectResponse(url="/admin/brands", status_code=303)


@router.post("/brands/{brand_id}/delete")
def admin_brand_delete(
    request: Request,
    brand_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
):
    brand = db.query(Brand).filter(Brand.id == brand_id).first()
    if brand:
        try:
            for p in db.query(Product).filter(Product.brand_id == brand.id).all():
                p.brand_id = None
            db.delete(brand)
            db.commit()
            cache.invalidate()
        except SQLAlchemyError as exc:
            db.rollback()
            log.exception("brand delete failed: %s", exc)
            request.session["flash_error"] = _COMMIT_ERROR_MSG

    return RedirectResponse(url="/admin/brands", status_code=303)