"""Админка: контент статичных страниц (картинки + тексты)."""
import logging

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_admin
from app.core.rendering import admin_templates
from app.data import cache
from app.data.settings import (
    SITE_CONTENT_GROUPS,
    SITE_CONTENT_KEYS,
    get_setting,
    set_setting,
)
from app.services.storage import (
    delete_site_image,
    save_site_image,
    site_image_info,
    site_image_public_url,
)
from app.utils.helpers import is_ajax

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/site", tags=["admin-site"])

_COMMIT_ERROR_MSG = (
    "Не удалось сохранить — временная ошибка базы данных. "
    "Попробуйте ещё раз через минуту."
)


@router.get("", response_class=HTMLResponse)
def admin_site_content(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
):
    pages_order: list[str] = []
    pages_map: dict[str, list[dict]] = {}

    for group in SITE_CONTENT_GROUPS:
        page_title = group.get("page", "Прочее")
        items = []
        for item in group["items"]:
            key = item["key"]
            value = get_setting(db, key)

            if item["type"] == "image":
                info = site_image_info(value)
                items.append({
                    **item,
                    "url": site_image_public_url(value),
                    "info": info,
                })
            else:
                items.append({**item, "value": value or ""})

        if page_title not in pages_map:
            pages_map[page_title] = []
            pages_order.append(page_title)

        pages_map[page_title].append({
            "title": group["title"],
            "items": items,
        })

    pages = [
        {
            "title": title,
            "slug": title.lower().replace(" ", "-"),
            "groups": pages_map[title],
            "items_count": sum(len(g["items"]) for g in pages_map[title]),
        }
        for title in pages_order
    ]

    flash_error = request.session.pop("flash_error", None)

    return admin_templates.TemplateResponse(request, "site_content.html", {
        "pages": pages,
        "flash_error": flash_error,
    })


@router.post("/{key}/image")
def admin_site_image_upload(
    request: Request,
    key: str,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
    image: UploadFile = File(None),
    remove: str = Form(None),
):
    ajax = is_ajax(request)

    item = SITE_CONTENT_KEYS.get(key)
    if not item or item["type"] != "image":
        if ajax:
            return JSONResponse({"ok": False, "error": "Неизвестный ключ."}, status_code=400)
        return RedirectResponse(url="/admin/site", status_code=303)

    old_filename = get_setting(db, key)

    if remove:
        try:
            set_setting(db, key, None)
            db.commit()
            delete_site_image(old_filename)
            cache.invalidate()
        except SQLAlchemyError as exc:
            db.rollback()
            log.exception("site image remove failed: %s", exc)
            if ajax:
                return JSONResponse({"ok": False, "error": _COMMIT_ERROR_MSG}, status_code=503)
            request.session["flash_error"] = _COMMIT_ERROR_MSG
            return RedirectResponse(url="/admin/site", status_code=303)

        if ajax:
            return JSONResponse({"ok": True, "removed": True, "url": None})
        return RedirectResponse(url="/admin/site", status_code=303)

    if image is None or not image.filename:
        if ajax:
            return JSONResponse({"ok": False, "error": "Файл не выбран."}, status_code=400)
        return RedirectResponse(url="/admin/site", status_code=303)

    new_filename, err = save_site_image(image, key)
    if err:
        if ajax:
            return JSONResponse({"ok": False, "error": err}, status_code=400)
        request.session["flash_error"] = err
        return RedirectResponse(url="/admin/site", status_code=303)

    if new_filename:
        try:
            set_setting(db, key, new_filename)
            db.commit()
            if old_filename and old_filename != new_filename:
                delete_site_image(old_filename)
            cache.invalidate()
        except SQLAlchemyError as exc:
            db.rollback()
            # Откат: новый файл уже на диске, но в Setting не попал.
            delete_site_image(new_filename)
            log.exception("site image save failed: %s", exc)
            if ajax:
                return JSONResponse({"ok": False, "error": _COMMIT_ERROR_MSG}, status_code=503)
            request.session["flash_error"] = _COMMIT_ERROR_MSG
            return RedirectResponse(url="/admin/site", status_code=303)

    info = site_image_info(new_filename)

    if ajax:
        return JSONResponse({
            "ok": True,
            "removed": False,
            "url": site_image_public_url(new_filename),
            "info": info,
        })
    return RedirectResponse(url="/admin/site", status_code=303)


@router.post("/{key}/text")
def admin_site_text_save(
    request: Request,
    key: str,
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
    value: str = Form(""),
):
    ajax = is_ajax(request)

    item = SITE_CONTENT_KEYS.get(key)
    if not item or item["type"] != "text":
        if ajax:
            return JSONResponse({"ok": False, "error": "Неизвестный ключ."}, status_code=400)
        return RedirectResponse(url="/admin/site", status_code=303)

    cleaned = value.strip() or None
    if cleaned and len(cleaned) > 200:
        cleaned = cleaned[:200]

    try:
        set_setting(db, key, cleaned)
        db.commit()
        cache.invalidate()
    except SQLAlchemyError as exc:
        db.rollback()
        log.exception("site text save failed: %s", exc)
        if ajax:
            return JSONResponse({"ok": False, "error": _COMMIT_ERROR_MSG}, status_code=503)
        request.session["flash_error"] = _COMMIT_ERROR_MSG
        return RedirectResponse(url="/admin/site", status_code=303)

    if ajax:
        return JSONResponse({"ok": True, "value": cleaned or ""})
    return RedirectResponse(url="/admin/site", status_code=303)