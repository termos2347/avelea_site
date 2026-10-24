"""Общие Jinja2-окружения и регистрация глобалов."""
from urllib.parse import quote

from markupsafe import Markup, escape
from fastapi.templating import Jinja2Templates

from app.core.config import BASE_DIR
from app.core.security import get_csrf_token
from app.services.storage import is_video
from app.utils.helpers import build_page_url, build_filter_url, build_reset_url


site_templates = Jinja2Templates(
    directory=BASE_DIR / "app" / "templates" / "site"
)
admin_templates = Jinja2Templates(
    directory=BASE_DIR / "app" / "templates" / "admin"
)


def _urlq(value) -> str:
    """URL-кодирование значения для подстановки в query-string."""
    return quote(str(value or ""), safe="")


site_templates.env.filters["urlq"] = _urlq


def _nav_categories() -> list[str]:
    from app.data import cache
    return [c.name for c in cache.get_categories()]


def _site_image(key: str, fallback: str = "") -> str:
    """URL картинки по ключу. Пусто если не загружена — без fallback."""
    from app.data import cache
    filename = cache.get_settings().get(key, "")
    if filename:
        return f"/static/site/{filename}"
    return fallback


def _site_text(key: str, default: str = "") -> Markup:
    """Текст из Setting. HTML экранируется, \\n → <br>.

    Возвращает Markup — Jinja вставит как безопасный HTML
    (там только наши <br>, пользовательский HTML уже escape'нут).
    """
    from app.data import cache
    value = cache.get_settings().get(key, "")
    if not value:
        value = default
    return Markup(escape(value).replace("\n", "<br>"))


site_templates.env.globals["build_page_url"] = build_page_url
site_templates.env.globals["build_filter_url"] = build_filter_url
site_templates.env.globals["build_reset_url"] = build_reset_url
site_templates.env.globals["csrf_token"] = get_csrf_token
site_templates.env.globals["is_video"] = is_video
site_templates.env.globals["nav_categories"] = _nav_categories
site_templates.env.globals["site_image"] = _site_image
site_templates.env.globals["site_text"] = _site_text


admin_templates.env.globals["csrf_token"] = get_csrf_token
admin_templates.env.globals["is_video"] = is_video