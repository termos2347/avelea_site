# Avelea Shop — интернет-магазин косметики

Проект на **Python + FastAPI** с минимальным JavaScript (только HTMX и Tailwind).  

---

## запуск

```bash
# Перейти в папку проекта
cd ~/avelea_site

# Активировать виртуальное окружение
./install.sh

# Запустить сервер
./start.sh
```

## Дерево файлов

```bash
avelea_site/
├── app/
│   ├── __init__.py          # Делает папку модулем Python
│   ├── main.py              # Главный файл приложения
│   ├── config.py            # Конфиг сайта
│   ├── models.py            # SQLAlchemy модели (таблицы БД)
│   ├── database.py          # Подключение к БД и сессии
│   ├── seed.py
│   └── templates/           # HTML шаблоны
│       ├── admin/           # HTML шаблоны админки
│       │   ├── base.html
│       │   ├── brands.html
│       │   ├── categories.html
│       │   ├── login.html
│       │   ├── _product_form.html
│       │   ├── product_form.html
│       │   ├── products.html
│       │   └── 404.html
│       └── site/            # HTML шаблоны сайта
│           ├── 404.html
│           ├── about.html
│           ├── base.html
│           ├── catalog.html
│           ├── index.html
│           └── product.html
├── static/
│   ├── css/
│   │   ├── admin.css
│   │   └── site.css
│   ├── js/
│   │   ├── admin.js
│   │   ├── catalog.js
│   │   └── site.js
│   └── uploads/
├── instance/
│   └── shop.db              # Файл SQLite
├── tests/
│   ├── conftest.py
│   ├── test_admin.py
│   └── test_smoke.py

├── .venv/                   # Виртуальное окружение
├── .gitignore               # Ну это .gitignore 
├── .env.example             # Настройки проекта 
├── requirements.txt         # Список зависимостей
├── main.py                  # Точка входа
├── start.sh                 # Скрипт для быстрого запуска
├── install.sh               # Скрипт для быстрой установки
└── README.md                # Этот файл
```