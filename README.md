# Avelea Shop — интернет-магазин косметики

Проект на **Python + FastAPI** с минимальным JavaScript (только HTMX и Tailwind).  

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
│   ├── main.py                 # Сборка приложения: FastAPI(), middleware,
│   │                           #   lifespan, exception handlers, роутеры
│   │
│   ├── core/                   # Инфраструктура (не зависит от бизнес-логики)
│   │   ├── config.py           # Чтение .env и константы
│   │   ├── database.py         # engine, SessionLocal, Base, get_db()
│   │   ├── deps.py             # FastAPI-зависимости: require_admin, CSRF
│   │   ├── middleware.py       # BodySizeLimitMiddleware
│   │   ├── ratelimit.py
│   │   └── rendering.py        # Jinja2-окружения + регистрация глобалов
│   │
│   ├── data/                   # Всё про данные
│   │   ├── models.py           # SQLAlchemy-модели: Product, Brand, Category
│   │   ├── migrations.py       # Идемпотентные миграции при старте
│   │   ├── seed.py             # Стартовые данные (только при пустой БД)
│   │   └── cache.py            # In-memory кэш товаров/категорий/брендов
│   │
│   ├── services/               # Внешние сервисы
│   │   └── storage.py          # Сохранение картинок (Local / S3)
│   │
│   ├── utils/                  # Чистые функции без состояния
│   │   └── helpers.py          # URL-билдеры, парсинг формы, resolve-хелперы
│   │
│   ├── routers/                # HTTP-роуты
│   │   ├── site.py             # Страницы: /, /catalog, /product, /about
│   │   └── admin/              # Админка
│   │       ├── auth.py         #   /admin/login, /admin/logout
│   │       ├── products.py     #   /admin/products/*
│   │       └── catalog.py      #   /admin/brands/*, /admin/categories/*
│   │
│   └── templates/              # HTML-шаблоны Jinja2
│       ├── admin/              #   Шаблоны админки
│       │   ├── base.html
│       │   ├── login.html
│       │   ├── products.html
│       │   ├── product_form.html
│       │   ├── _product_form.html
│       │   ├── brands.html
│       │   ├── categories.html
│       │   └── 404.html
│       └── site/               #   Шаблоны публичной части
│           ├── _macros.html
│           ├── base.html
│           ├── index.html
│           ├── catalog.html
│           ├── product.html
│           ├── about.html
│           └── 404.html
│
├── static/
│   ├── css/
│   │   ├── admin.css
│   │   └── site.css
│   ├── js/
│   │   ├── admin.js
│   │   ├── catalog.js
│   │   └── site.js
│   └── uploads/                # Загруженные картинки товаров
│
├── instance/
│   └── shop.db                 # Файл SQLite (если DATABASE_URL не задан)
│
├── tests/
│   ├── conftest.py             # Фикстуры: TestClient, admin_client, CSRF
│   ├── test_smoke.py           # Публичные страницы: главная, каталог, товар
│   └── test_admin.py           # Админка: логин, CSRF, CRUD, загрузки, валидация
│   └── test_migrations.py
│
├── .venv/                      # Виртуальное окружение
├── .gitignore
├── .env.example                # Шаблон настроек
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