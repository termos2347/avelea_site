#!/usr/bin/env bash
# start.sh — активирует виртуальное окружение и запускает проект
set -e

# Всегда работаем из директории скрипта
cd "$(dirname "$0")"

# 0. Проверяем наличие .env
if [ ! -f ".env" ]; then
    echo "❌ Файл .env не найден." >&2
    echo "   Скопируйте шаблон:  cp .env.example .env" >&2
    echo "   И заполните SECRET_KEY и ADMIN_PASSWORD." >&2
    exit 1
fi

# 1. Проверяем, что .venv существует
if [ ! -d ".venv" ]; then
    echo "❌ Виртуальное окружение .venv не найдено." >&2
    echo "   Сначала выполните: ./install.sh" >&2
    exit 1
fi

# 2. Проверяем точку входа
if [ ! -f "run.py" ]; then
    echo "❌ Не найден run.py в $(pwd)" >&2
    exit 1
fi

# 3. Активируем venv
# shellcheck disable=SC1091
source .venv/bin/activate

# 4. Небольшая диагностика — полезно при отладке
echo "=== Запуск проекта ==="
echo "Python:  $(command -v python) ($(python --version 2>&1))"
echo "Каталог: $(pwd)"
echo ""

# 5. exec заменяет процесс bash процессом python —
#    это корректно передаёт сигналы (Ctrl+C, SIGTERM) самому приложению
exec python run.py