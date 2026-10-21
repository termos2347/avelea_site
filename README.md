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

## ⚠️ Один воркер
In-memory state — кэш товаров, rate-limiter логина, хранилище 2FA-кодов —
живёт в памяти процесса. При UVICORN_WORKERS > 1:

2FA ломается (код выдан на воркере A, проверяется на воркере B);

rate-limit обходится (у каждого воркера свой счётчик);

cache.invalidate() не виден другим воркерам (отдаётся старьё);

Alembic в lifespan запускается N раз параллельно.

Поэтому UVICORN_WORKERS=1 (значение по умолчанию). Для масштабирования
на несколько процессов — сначала вынести state в Redis.

---

## 🚀 Деплой в прод

Раздел для тех, кто впервые выкатывает проект на сервер и не хочет
наступить на типовые грабли. Локально всё это **не нужно** — здесь про
боевой запуск.

### Что поменять в `.env` на проде

| Переменная | Локально | В проде | Почему |
|---|---|---|---|
| `UVICORN_RELOAD` | `true` | **`false`** | Reload следит за файлами (в проде их никто не меняет), плодит второй процесс. In-memory state (кэш, rate-limit, 2FA-коды) **не шарится** между процессами → 2FA и rate-limit ломаются |
| `UVICORN_WORKERS` | `1` | **`1`** | Та же причина. Для >1 сначала вынести state в Redis |
| `AUTO_MIGRATE` | `true` | **`false`** | Миграции запускать отдельно (`alembic upgrade head`) перед рестартом. Иначе при падении миграции сервис не стартует — хорошо, но лучше контролировать руками |
| `SESSION_HTTPS_ONLY` | `false` | **`true`** | Cookie только по HTTPS + HSTS-заголовок. Без этого сессия уедет по HTTP |
| `SEED_DEMO_PRODUCT` | `1` (для тестов) | **`0`** | Демо-товар «Древесный парфюм» не нужен в проде |
| `DATABASE_URL` | локальный Postgres | **с `?sslmode=require`** | Облачный Postgres (Neon, Supabase) требует TLS |
| `SECRET_KEY` | любой | **64+ случайных** | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `ADMIN_PASSWORD` | `test-password-123` | **16+ символов, не из словаря** | Это единственный барьер перед админкой, если 2FA выключен |

**Проверить одним глазом:**

```bash
grep -E '^(UVICORN_RELOAD|UVICORN_WORKERS|AUTO_MIGRATE|SESSION_HTTPS_ONLY|SEED_DEMO_PRODUCT)=' .env
```

Ожидаемо на проде:

```
UVICORN_RELOAD=false
UVICORN_WORKERS=1
AUTO_MIGRATE=false
SESSION_HTTPS_ONLY=true
SEED_DEMO_PRODUCT=0
```

### Systemd unit — пример

Файл `/etc/systemd/system/avelea.service`:

```ini
[Unit]
Description=Avelea shop
After=network.target

[Service]
Type=simple
User=avelea
Group=avelea
WorkingDirectory=/home/avelea/avelea_site
EnvironmentFile=/home/avelea/avelea_site/.env
ExecStart=/home/avelea/avelea_site/.venv/bin/python run.py

# Перезапускать при падении, но не бесконечно.
# StartLimit* — критично: без них systemd будет долбиться
# вечно, если сервис падает на старте (например,
# AUTO_MIGRATE=false и БД отстаёт от head).
Restart=on-failure
RestartSec=30
StartLimitBurst=3
StartLimitIntervalSec=300

# Логи — в journald. Смотреть: journalctl -u avelea -f
StandardOutput=journal
StandardError=journal

# Базовая изоляция
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/home/avelea/avelea_site/instance /home/avelea/avelea_site/static/uploads /home/avelea/avelea_site/static/site

[Install]
WantedBy=multi-user.target
```

**Что делает `StartLimitBurst=3` + `StartLimitIntervalSec=300`:**
не более 3 перезапусков за 5 минут. Если сервис падает 3 раза подряд — systemd
**перестаёт его перезапускать** и оставляет в статусе `failed`. Это правильно:
лучше увидеть `failed` и разобраться, чем наблюдать, как сервис падает в цикле
и жрёт CPU.

**Первичная установка:**

```bash
sudo systemctl daemon-reload
sudo systemctl enable avelea
sudo systemctl start avelea
sudo systemctl status avelea
```

**После `git pull` + изменения `.env` или миграций:**

```bash
# 1. Накатить миграции (если AUTO_MIGRATE=false)
cd /home/avelea/avelea_site
.venv/bin/alembic upgrade head

# 2. Перезапустить сервис
sudo systemctl restart avelea

# 3. Посмотреть, что стартануло
sudo journalctl -u avelea -n 30 --no-pager
```

### Если сервис упал — что смотреть

```bash
# Статус и код последнего завершения
sudo systemctl status avelea

# Логи за последние 5 минут
sudo journalctl -u avelea --since "5 min ago" --no-pager

# Только ошибки
sudo journalctl -u avelea -p err -n 50 --no-pager

# Следить в реальном времени
sudo journalctl -u avelea -f
```

**Типовые сообщения и что делать:**

| В логе | Причина | Что делать |
|---|---|---|
| `Миграции не применены: current=..., head=...` | `AUTO_MIGRATE=false`, БД отстаёт | `.venv/bin/alembic upgrade head` → `systemctl restart avelea` |
| `❌ Переменная SECRET_KEY не задана` | `.env` не найден или пустой | Проверить `EnvironmentFile=` в unit, права на файл |
| `❌ Файл .env не найден` (из `start.sh`) | Сервис запущен не через systemd, а руками из чужой папки | Проверить `WorkingDirectory=` |
| `Address already in use` | Порт 8000 занят другим процессом | `sudo ss -tlnp \| grep 8000` — найти и убить |
| `Application startup failed. Exiting.` + стектрейс | Что-то упало в lifespan (БД недоступна, миграции, seed) | Читать строку **над** стектрейсом — там ERROR от `avelea`-логгера |

### Локально vs прод — короткая шпаргалка

| | Локально | В проде |
|---|---|---|
| Запуск | `./start.sh` | `sudo systemctl start avelea` |
| Логи | терминал | `journalctl -u avelea -f` |
| `UVICORN_RELOAD` | `true` — удобно | `false` — обязательно |
| Миграции | автоматом при старте (`AUTO_MIGRATE=true`) | вручную `alembic upgrade head` |
| Порт | 8000 напрямую | 8000 за nginx (443 → 8000) |
| HTTPS | нет | nginx + certbot |
| `SESSION_HTTPS_ONLY` | `false` | `true` |


### Ротация SECRET_KEY

`SECRET_KEY` подписывает cookie сессии. При смене **все активные сессии
инвалидируются** — все, кто был в админке, выйдут. Для витрины это только
админ, покупателей нет.

**Когда ротировать:**
- При подозрении на утечку `.env` (закоммичен, показан в скриншоте, отдан подрядчику).
- Раз в год — профилактически.
- После увольнения сотрудника с доступом к серверу.

**Как:**

```bash
# 1. Сгенерировать новый ключ
python -c "import secrets; print(secrets.token_urlsafe(48))"

# 2. Заменить в .env
sed -i 's|^SECRET_KEY=.*|SECRET_KEY=<новый>|' .env

# 3. Перезапустить сервис
sudo systemctl restart avelea

# 4. Зайти в админку заново (/admin/login)
```

**Что НЕ ломается:** товары, категории, бренды, настройки, картинки —
всё в БД и на диске, `SECRET_KEY` их не касается.

**Что ломается:** активные сессии (нужно перелогиниться), незавершённые
2FA-логины (нужно получить новый код в Telegram).

---

## Структура проекта
```bash
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
│   │   ├── security.py             # CSRF, require_admin, rate-limit логина
│   │   ├── middleware.py           # BodySizeLimit, SecurityHeaders, AdminAuthGuard,
│   │   │                           #   StaticCache
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
│   ├── conftest.py                 # Фикстуры: TestClient, admin_client, CSRF, очистка uploads
│   ├── test_smoke.py               # Публичные страницы, robots.txt, sitemap.xml, 404
│   └── test_admin.py               # Админка: логин, CSRF, 2FA, CRUD, загрузки, откаты
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