# Avelea — витрина косметики

Каталог товаров на **Python + FastAPI** с админкой и минимальным
JavaScript (HTMX + Tailwind). Без корзины, без оплаты, без личного
кабинета — только публичный каталог и панель управления.

**База данных — PostgreSQL** (облачный инстанс: Neon, Supabase,
Selectel, VK Cloud, RDS — любой провайдер). Драйвер — `psycopg3`.

---

![Python](https://img.shields.io/badge/python-3.12-blue)
![Tests](https://img.shields.io/badge/tests-passed-brightgreen)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688)
![Alembic](https://img.shields.io/badge/Alembic-1.14-blue)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15%2B-336791)

## Требования

- Python 3.12+
- PostgreSQL 15+ (локально или облачный инстанс)
- Node.js — опционально, только если хочется собрать Tailwind локально
  (сейчас стили тянутся с CDN, для витрины это работает «из коробки»)

## Запуск

```bash
# Перейти в папку проекта
cd ~/avelea_site

# Первый раз — установить зависимости и создать .venv
./install.sh

# Скопировать шаблон и заполнить секреты
cp .env.example .env
# (отредактировать SECRET_KEY, ADMIN_PASSWORD и DATABASE_URL)

# Запустить сервер
./start.sh
```

## Локальный запуск
```bash
npx localtunnel --port 8000 --subdomain avelea-test
```

---

## Структура проекта

avelea_site/
├── alembic.ini                     # Конфиг Alembic (URL берётся из .env)
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI(): middleware, lifespan, exception
│   │                               #   handlers, /robots.txt, /sitemap.xml, роутеры
│   │
│   ├── core/                       # Инфраструктура (не зависит от бизнес-логики)
│   │   ├── config.py               # Чтение .env и константы
│   │   ├── database.py             # engine (Postgres pool), SessionLocal, Base, get_db()
│   │   ├── deps.py                 # FastAPI-зависимости: require_admin, CSRF
│   │   ├── middleware.py           # BodySizeLimit, SecurityHeaders, AdminAuthGuard,
│   │   │                           #   StaticCache
│   │   ├── ratelimit.py            # In-memory rate-limiter для /admin/login
│   │   └── rendering.py            # Jinja2-окружения + регистрация глобалов
│   │
│   ├── data/                       # Всё про данные
│   │   ├── models.py               # SQLAlchemy: Product, ProductVariant, Brand,
│   │   │                           #   Category, Setting
│   │   ├── seed.py                 # Стартовые данные (флаг в Setting, демо — опционально)
│   │   ├── settings.py             # Реестр настроек сайта (SITE_CONTENT_GROUPS)
│   │   └── cache.py                # In-memory кэш товаров/категорий/брендов
│   │
│   ├── services/                   # Внешние сервисы
│   │   └── storage.py              # Сохранение картинок/видео (Local / S3) + WebP
│   │
│   ├── utils/                      # Чистые функции без состояния
│   │   └── helpers.py              # URL-билдеры, парсинг формы, resolve-хелперы
│   │
│   ├── routers/                    # HTTP-роуты
│   │   ├── site.py                 # /, /catalog, /product, /brands, /about
│   │   └── admin/
│   │       ├── auth.py             #   /admin/login (+ Telegram 2FA), /admin/logout
│   │       ├── products.py         #   /admin/products/*
│   │       ├── catalog.py          #   /admin/brands/*, /admin/categories/*
│   │       └── site_content.py     #   /admin/site/* (картинки + тексты статических страниц)
│   │
│   └── templates/                  # Jinja2-шаблоны
│       ├── admin/
│       │   ├── base.html           #   Каркас: топбар, модалки, saving-overlay
│       │   ├── login.html          #   Вход: шаг 1 — пароль, шаг 2 — код из Telegram
│       │   ├── products.html       #   Список (таблица / карточки)
│       │   ├── product_form.html   #   Отдельная страница формы товара
│       │   ├── _product_form.html  #   Общая форма (для /new и /edit)
│       │   ├── brands.html
│       │   ├── categories.html
│       │   ├── site_content.html   #   Управление контентом публичных страниц
│       │   └── error.html          #   Универсальная страница (404 / 500 / 413 / …)
│       └── site/
│           ├── _macros.html        #   Макрос product_card
│           ├── base.html           #   Каркас: nav, footer, OG-теги, favicon, скелетон
│           ├── index.html          #   Главная (hero-карусель, категории, популярное)
│           ├── catalog.html        #   Каталог с фильтрами
│           ├── product.html        #   Карточка товара
│           ├── brands.html         #   Алфавитный указатель брендов
│           ├── about.html
│           └── error.html          #   Универсальная страница ошибки
│
├── static/
│   ├── css/
│   │   ├── admin.css
│   │   └── site.css
│   ├── js/
│   │   ├── admin.js                # Модалки, форма, debounce, saving-overlay
│   │   ├── catalog.js              # Модал фильтров каталога
│   │   └── site.js                 # Скелетон, hero-карусель, рейлы карточек
│   ├── uploads/                    # Загруженные картинки товаров (в .gitignore)
│   └── site/                       # Картинки страниц сайта (в .gitignore)
│
├── instance/
│   └── logs/
│       └── avelea.log              # Ротируемый лог приложения
│
├── migrations/                     # ← Alembic
│   ├── env.py                      # Настройка: target_metadata, render_as_batch
│   ├── script.py.mako              # Шаблон для новых миграций
│   └── versions/
│       └── f63c89e8e32f_initial_schema.py   # Baseline (создаёт всю схему)
│
├── tests/
│   ├── conftest.py                 # Фикстуры: TestClient, admin_client, CSRF
│   ├── test_smoke.py               # Публичные страницы, robots.txt, sitemap.xml, 404
│   └── test_admin.py               # Админка: логин, CSRF, 2FA, CRUD, загрузки
│
├── .venv/                          # Виртуальное окружение (в .gitignore)
├── .gitignore
├── .env.example                    # Шаблон настроек
├── .env                            # Боевые секреты (в .gitignore)
├── requirements.txt
├── run.py                          # Точка входа: uvicorn.run("app.main:app")
├── start.sh                        # Запуск сервера (активация venv + python run.py)
├── install.sh                      # Создание venv + установка зависимостей
└── README.md

---

## Карта: куда идти при типовых задачах

| Задача | Файл |
|---|---|
| Добавить страницу на сайт | `app/routers/site.py` |
| Изменить список товаров в админке | `app/routers/admin/products.py` |
| Добавить раздел в админке | новый файл в `app/routers/admin/` |
| Добавить поле в товар | `app/data/models.py` + `app/routers/admin/products.py` + `_product_form.html` |
| Изменить фильтры каталога | `app/routers/site.py` + `app/utils/helpers.py` |
| Изменить защиту от CSRF | `app/core/deps.py` |
| Добавить настройку через `.env` | `app/core/config.py` |
| Изменить миграции БД | `app/data/migrations.py` |
| Изменить стартовые данные | `app/data/seed.py` |
| Поменять хранилище картинок | `app/services/storage.py` |
| Изменить security-заголовки | `app/core/middleware.py` |
| Настроить Telegram 2FA | `app/routers/admin/auth.py` + `.env` |
| Изменить страницы ошибок | `app/main.py` (`_ERROR_PAGES`, `_pick_error_preset`) |
| Изменить тексты страниц ошибок | `app/main.py` → `_ERROR_PAGES` |