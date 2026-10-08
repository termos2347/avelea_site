"""Авторизация в админке: логин, логаут, редирект с /admin."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.config import ADMIN_PASSWORD
from app.core.deps import check_csrf, safe_str_compare
from app.core.rendering import admin_templates

router = APIRouter(prefix="/admin", tags=["admin-auth"])


@router.get("/login", response_class=HTMLResponse)
async def admin_login_form(request: Request):
    if request.session.get("admin"):
        return RedirectResponse(url="/admin/products", status_code=303)
    return admin_templates.TemplateResponse(request, "login.html", {
        "error": None,
    })


@router.post("/login", dependencies=[Depends(check_csrf)])
async def admin_login_submit(request: Request, password: str = Form(...)):
    if safe_str_compare(password, ADMIN_PASSWORD):
        request.session["admin"] = True
        return RedirectResponse(url="/admin/products", status_code=303)
    return admin_templates.TemplateResponse(
        request, "login.html",
        {"error": "Неверный пароль"},
        status_code=401,
    )


@router.get("/logout")
async def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=303)


@router.get("", response_class=HTMLResponse)
async def admin_root(request: Request):
    return RedirectResponse(url="/admin/products", status_code=303)