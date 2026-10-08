"""Админка: бренды и категории."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.data import cache
from app.core.database import get_db
from app.core.deps import require_admin
from app.data.models import Product, Brand, Category, product_categories
from app.core.rendering import admin_templates

router = APIRouter(prefix="/admin", tags=["admin-catalog"])


# ============================================================
# Категории
# ============================================================

@router.get("/categories", response_class=HTMLResponse)
async def admin_categories(
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
async def admin_category_create(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
    name: str = Form(...),
):
    name = name.strip()
    if name:
        exists = db.query(Category).filter(Category.name == name).first()
        if exists:
            request.session["flash_error"] = f"Категория «{name}» уже существует."
        else:
            db.add(Category(name=name))
            db.commit()
            cache.invalidate()
    return RedirectResponse(url="/admin/categories", status_code=303)


@router.post("/categories/{category_id}/edit")
async def admin_category_edit(
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
    if name and name != category.name:
        exists = (
            db.query(Category)
              .filter(Category.name == name, Category.id != category_id)
              .first()
        )
        if exists:
            request.session["flash_error"] = f"Категория «{name}» уже существует."
        else:
            category.name = name
            db.commit()
            cache.invalidate()
    return RedirectResponse(url="/admin/categories", status_code=303)


@router.post("/categories/{category_id}/delete")
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
        cache.invalidate()
    return RedirectResponse(url="/admin/categories", status_code=303)


# ============================================================
# Бренды
# ============================================================

@router.get("/brands", response_class=HTMLResponse)
async def admin_brands(
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
async def admin_brand_create(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
    name: str = Form(...),
):
    name = name.strip()
    if name:
        exists = db.query(Brand).filter(Brand.name == name).first()
        if exists:
            request.session["flash_error"] = f"Бренд «{name}» уже существует."
        else:
            db.add(Brand(name=name))
            db.commit()
            cache.invalidate()
    return RedirectResponse(url="/admin/brands", status_code=303)


@router.post("/brands/{brand_id}/edit")
async def admin_brand_edit(
    request: Request,
    brand_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
    name: str = Form(...),
):
    brand = db.query(Brand).filter(Brand.id == brand_id).first()
    if not brand:
        raise HTTPException(status_code=404)

    name = name.strip()
    if name and name != brand.name:
        exists = (
            db.query(Brand)
              .filter(Brand.name == name, Brand.id != brand_id)
              .first()
        )
        if exists:
            request.session["flash_error"] = f"Бренд «{name}» уже существует."
        else:
            brand.name = name
            db.commit()
            cache.invalidate()
    return RedirectResponse(url="/admin/brands", status_code=303)


@router.post("/brands/{brand_id}/delete")
async def admin_brand_delete(
    request: Request,
    brand_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
):
    brand = db.query(Brand).filter(Brand.id == brand_id).first()
    if brand:
        for p in db.query(Product).filter(Product.brand_id == brand.id).all():
            p.brand_id = None
        db.delete(brand)
        db.commit()
        cache.invalidate()
    return RedirectResponse(url="/admin/brands", status_code=303)