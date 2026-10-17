"""Хелперы для key-value настроек сайта."""
from sqlalchemy.orm import Session

from app.data.models import Setting


SITE_CONTENT_GROUPS: list[dict] = [
    {
        "title": "Главная — Hero слайд 1",
        "items": [
            {"type": "image", "key": "home_hero_1_image", "label": "Фон"},
            {"type": "text", "key": "home_hero_1_eyebrow", "label": "Надзаголовок",
             "default": "Новая коллекция"},
            {"type": "text", "key": "home_hero_1_title", "label": "Заголовок",
             "multiline": True, "default": "Натуральная косметика\nдля вашей кожи"},
            {"type": "text", "key": "home_hero_1_subtitle", "label": "Подзаголовок",
             "multiline": True,
             "default": "Подобранные средства из чистых ингредиентов. Без парабенов, без жестокости, с любовью."},
            {"type": "text", "key": "home_hero_1_button", "label": "Текст кнопки",
             "default": "Смотреть каталог"},
        ],
    },
    {
        "title": "Главная — Hero слайд 2",
        "items": [
            {"type": "image", "key": "home_hero_2_image", "label": "Фон"},
            {"type": "text", "key": "home_hero_2_eyebrow", "label": "Надзаголовок",
             "default": "Специальное предложение"},
            {"type": "text", "key": "home_hero_2_title", "label": "Заголовок",
             "multiline": True, "default": "−20% на первый\nзаказ"},
            {"type": "text", "key": "home_hero_2_subtitle", "label": "Подзаголовок",
             "multiline": True,
             "default": "Подберите уход и получите скидку на всё. Доставка по России — бесплатно от 3000 ₽."},
            {"type": "text", "key": "home_hero_2_button", "label": "Текст кнопки",
             "default": "За покупками"},
        ],
    },
    {
        "title": "Главная — Hero слайд 3",
        "items": [
            {"type": "image", "key": "home_hero_3_image", "label": "Фон"},
            {"type": "text", "key": "home_hero_3_eyebrow", "label": "Надзаголовок",
             "default": "Новинки сезона"},
            {"type": "text", "key": "home_hero_3_title", "label": "Заголовок",
             "multiline": True, "default": "Уход, который\nвлюбляет"},
            {"type": "text", "key": "home_hero_3_subtitle", "label": "Подзаголовок",
             "multiline": True,
             "default": "Свежие формулы с витаминами и растительными маслами. Уже в каталоге."},
            {"type": "text", "key": "home_hero_3_button", "label": "Текст кнопки",
             "default": "Узнать больше"},
        ],
    },
    {
        "title": "Главная — Плитки категорий",
        "items": [
            {"type": "image", "key": "home_category_face_image",    "label": "Категория «Лицо»"},
            {"type": "image", "key": "home_category_makeup_image",  "label": "Категория «Макияж»"},
            {"type": "image", "key": "home_category_body_image",    "label": "Категория «Тело»"},
            {"type": "image", "key": "home_category_perfume_image", "label": "Категория «Парфюм»"},
        ],
    },
    {
        "title": "Каталог",
        "items": [
            {"type": "image", "key": "catalog_banner_image",
             "label": "Баннер сверху (и заглушка «ничего не найдено»)"},
        ],
    },
    {
        "title": "О нас — Hero",
        "items": [
            {"type": "image", "key": "about_hero_image", "label": "Фон"},
            {"type": "text", "key": "about_hero_eyebrow", "label": "Надзаголовок",
             "default": "Наша история"},
            {"type": "text", "key": "about_hero_title", "label": "Заголовок",
             "multiline": True, "default": "Начали с любви\nк красоте"},
            {"type": "text", "key": "about_hero_subtitle", "label": "Подзаголовок",
             "multiline": True,
             "default": "AVELEA родилась из простой идеи — сделать мировую бьюти-индустрию ближе и доступнее."},
        ],
    },
    {
        "title": "О нас — Блоки",
        "items": [
            {"type": "image", "key": "about_idea_image",  "label": "Картинка «Пространство красоты»"},
            {"type": "image", "key": "about_world_image", "label": "Картинка «Коллекция»"},
            {"type": "text", "key": "about_cta_title", "label": "CTA — заголовок",
             "default": "Готовы попробовать?"},
            {"type": "text", "key": "about_cta_subtitle", "label": "CTA — подзаголовок",
             "multiline": True,
             "default": "Откройте каталог и найдите уход, который полюбит ваша кожа."},
            {"type": "text", "key": "about_cta_button", "label": "CTA — кнопка",
             "default": "Смотреть каталог"},
        ],
    },
    {
        "title": "Футер",
        "items": [
            {"type": "text", "key": "footer_phone", "label": "Телефон",
             "default": "+7 962 573 0996"},
            {"type": "text", "key": "footer_email", "label": "Email",
             "default": "avelea_store@gmail.com"},
            {"type": "text", "key": "footer_address", "label": "Адрес",
             "default": "г. Нижнекамск"},
            {"type": "text", "key": "footer_hours", "label": "Часы работы",
             "default": "Пн–Пт, 10:00–19:00"},
            {"type": "text", "key": "footer_copyright", "label": "Копирайт",
             "default": "© 2026 avelea. Все права защищены."},
        ],
    },
]


SITE_CONTENT_KEYS: dict[str, dict] = {
    item["key"]: item
    for group in SITE_CONTENT_GROUPS
    for item in group["items"]
}


def get_setting(db: Session, key: str) -> str | None:
    s = db.query(Setting).filter(Setting.key == key).first()
    return s.value if s else None


def set_setting(db: Session, key: str, value: str | None) -> None:
    s = db.query(Setting).filter(Setting.key == key).first()
    if s is None:
        db.add(Setting(key=key, value=value))
    else:
        s.value = value