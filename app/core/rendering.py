"""Общие Jinja2-окружения и регистрация глобалов.

Импортируется один раз; повторный импорт вернёт те же объекты.
"""
from fastapi.templating import Jinja2Templates

from app.core.config import BASE_DIR
from app.core.deps import get_csrf_token
from app.utils.helpers import build_page_url, build_filter_url, build_reset_url


site_templates = Jinja2Templates(
    directory=BASE_DIR / "app" / "templates" / "site"
)
admin_templates = Jinja2Templates(
    directory=BASE_DIR / "app" / "templates" / "admin"
)

# --- Публичная часть ---
site_templates.env.globals["build_page_url"] = build_page_url
site_templates.env.globals["build_filter_url"] = build_filter_url
site_templates.env.globals["build_reset_url"] = build_reset_url
site_templates.env.globals["csrf_token"] = get_csrf_token

# --- Админка ---
admin_templates.env.globals["csrf_token"] = get_csrf_token