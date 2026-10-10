# Avelea — витрина косметики

Каталог товаров на **Python + FastAPI** с админкой и минимальным
JavaScript (HTMX + Tailwind). Без корзины, без оплаты, без личного
кабинета — только публичный каталог и панель управления.
---

## Запуск

```bash
# Перейти в папку проекта
cd ~/avelea_site

npx localtunnel --port 8000 --subdomain avelea-test

# Активировать виртуальное окружение
./install.sh

# Запустить сервер
./start.sh
```

Перед первым запуском скопируйте `.env.example` в `.env` и заполните
`SECRET_KEY` и `ADMIN_PASSWORD`.

---

## Структура проекта

```
avelea_site/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI(): middleware, lifespan, exception
│   │                           #   handlers, /robots.txt, /sitemap.xml, роутеры
│   │
│   ├── core/                   # Инфраструктура (не зависит от бизнес-логики)
│   │   ├── config.py           # Чтение .env и константы
│   │   ├── database.py         # engine, SessionLocal, Base, get_db()
│   │   ├── deps.py             # FastAPI-зависимости: require_admin, CSRF
│   │   ├── middleware.py       # BodySizeLimit, SecurityHeaders, AdminAuthGuard
│   │   ├── ratelimit.py        # In-memory rate-limiter для /admin/login
│   │   └── rendering.py        # Jinja2-окружения + регистрация глобалов
│   │
│   ├── data/                   # Всё про данные
│   │   ├── models.py           # SQLAlchemy: Product, Brand, Category, Setting
│   │   ├── migrations.py       # Идемпотентные миграции при старте
│   │   ├── seed.py             # Стартовые данные (один раз, флаг в Setting)
│   │   └── cache.py            # In-memory кэш товаров/категорий/брендов
│   │
│   ├── services/               # Внешние сервисы
│   │   └── storage.py          # Сохранение картинок (Local / S3) + ресайз
│   │
│   ├── utils/                  # Чистые функции без состояния
│   │   └── helpers.py          # URL-билдеры, парсинг формы, resolve-хелперы
│   │
│   ├── routers/                # HTTP-роуты
│   │   ├── site.py             # /, /catalog, /product, /about
│   │   └── admin/              # Админка
│   │       ├── auth.py         #   /admin/login (+ Telegram 2FA), /admin/logout
│   │       ├── products.py     #   /admin/products/*
│   │       └── catalog.py      #   /admin/brands/*, /admin/categories/*
│   │
│   └── templates/              # Jinja2-шаблоны
│       ├── admin/
│       │   ├── base.html       #   Каркас: топбар, модалки, saving-overlay
│       │   ├── login.html      #   Вход: шаг 1 — пароль, шаг 2 — код из Telegram
│       │   ├── products.html   #   Список (таблица / карточки)
│       │   ├── product_form.html   # Отдельная страница формы товара
│       │   ├── _product_form.html  # Общая форма (для /new и /edit)
│       │   ├── brands.html
│       │   ├── categories.html
│       │   └── error.html      #   Универсальная страница (404 / 500 / 413 / …)
│       └── site/
│           ├── _macros.html    #   Макрос product_card
│           ├── base.html       #   Каркас: nav, footer, OG-теги, favicon, скелетон
│           ├── index.html      #   Главная (hero-карусель, категории, популярное)
│           ├── catalog.html    #   Каталог с фильтрами
│           ├── product.html    #   Карточка товара
│           ├── about.html
│           └── error.html      #   Универсальная страница ошибки
│
├── static/
│   ├── css/
│   │   ├── admin.css
│   │   └── site.css
│   ├── js/
│   │   ├── admin.js            # Модалки, форма, debounce, saving-overlay
│   │   ├── catalog.js          # Модал фильтров каталога
│   │   └── site.js             # Скелетон, hero-карусель, рейлы карточек
│   └── uploads/                # Загруженные картинки (в .gitignore)
│
├── instance/
│   └── shop.db                 # SQLite, если DATABASE_URL не задан (в .gitignore)
│
├── tests/
│   ├── conftest.py             # Фикстуры: TestClient, admin_client, CSRF
│   ├── test_smoke.py           # Публичные страницы, robots.txt, sitemap.xml, 404
│   ├── test_admin.py           # Админка: логин, CSRF, 2FA, CRUD, загрузки
│   └── test_migrations.py      # Миграции схемы на «старой» БД
│
├── .venv/                      # Виртуальное окружение (в .gitignore)
├── .gitignore
├── .env.example                # Шаблон настроек
├── .env                        # Боевые секреты (в .gitignore)
├── requirements.txt
├── run.py                      # Точка входа: uvicorn.run("app.main:app")
├── start.sh                    # Запуск сервера
├── install.sh                  # Создание venv + установка зависимостей
└── README.md
```

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