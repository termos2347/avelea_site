# Avelea Shop — интернет-магазин косметики

Проект на **Python + FastAPI** с минимальным JavaScript (только HTMX и Tailwind).  
Подходит для небольшого магазина с каталогом, фильтрами, корзиной и страницей "О нас".

---

## 🚀 Быстрый запуск

```bash
# Перейти в папку проекта
cd ~/avelea_site

# Активировать виртуальное окружение
source venv/bin/activate

# Установить зависимости (если ещё не установлены)
pip install -r requirements.txt

# Запустить сервер
python main.py


avelea_site/
├── app/
│   ├── __init__.py          # Делает папку модулем Python
│   ├── main.py              # Главный файл приложения (роуты, логика)
│   ├── models.py            # SQLAlchemy модели (таблицы БД)
│   ├── database.py          # Подключение к БД и сессии
│   └── templates/           # HTML-шаблоны (Jinja2)
│       ├── base.html        # Базовый шаблон (навигация, футер)
│       ├── index.html       # Главная страница
│       ├── catalog.html     # Каталог с фильтрами
│       ├── product.html     # Страница товара
│       ├── cart.html        # Корзина
│       └── about.html       # Страница "О нас"
├── instance/
│   └── shop.db              # Файл SQLite (создаётся автоматически)
├── .venv/                    # Виртуальное окружение (не в репозитории)
├── .env                 # Скрипт для быстрого запуска (на NixOS)
├── requirements.txt         # Список зависимостей
├── main.py                  # Точка входа (запуск uvicorn)
├── start.sh                 # Скрипт для быстрого запуска (на NixOS)
├── install.sh                 # Скрипт для быстрого запуска (на NixOS)
└── README.md                # Этот файл