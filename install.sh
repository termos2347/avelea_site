#!/usr/bin/env bash
# install.sh — создаёт виртуальное окружение и устанавливает зависимости
set -e

# Всегда работаем из директории скрипта (важно для относительных путей)
cd "$(dirname "$0")"

# Разбор аргументов
FORCE=0
for arg in "$@"; do
    case "$arg" in
        -f|--force) FORCE=1 ;;
        -h|--help)
            cat <<EOF
Использование: $0 [-f|--force]

  -f, --force   удалить существующий .venv и создать заново
  -h, --help    показать эту справку
EOF
            exit 0
            ;;
        *)
            echo "Неизвестный аргумент: $arg" >&2
            exit 1
            ;;
    esac
done

echo "=== Проверка системного Python ==="

PYTHON_BIN=""
if command -v python3.13 >/dev/null 2>&1; then
    PYTHON_BIN=$(command -v python3.13)
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=$(command -v python3)
fi

if [ -z "$PYTHON_BIN" ]; then
    echo "❌ Python 3 не найден в системе." >&2
    echo "   Установите Python 3.10+ и повторите." >&2
    exit 1
fi

# Требуем Python >= 3.10 (нужно для | в аннотациях типов и др.)
if ! "$PYTHON_BIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "❌ Требуется Python 3.10 или новее. Найден: $("$PYTHON_BIN" --version 2>&1)" >&2
    exit 1
fi

echo "Используется: $PYTHON_BIN ($("$PYTHON_BIN" --version 2>&1))"

echo "=== Подготовка виртуального окружения ==="

if [ "$FORCE" -eq 1 ] && [ -d ".venv" ]; then
    echo "Удаляем существующий .venv (--force)..."
    rm -rf .venv
fi

if [ -d ".venv" ]; then
    echo "Виртуальное окружение .venv уже существует — переиспользуем."
else
    echo "Создаём .venv..."
    "$PYTHON_BIN" -m venv .venv
fi

# Активируем venv (внутри этого скрипта — на родительскую оболочку не влияет)
# shellcheck disable=SC1091
source .venv/bin/activate

echo "=== Обновление pip / setuptools / wheel ==="
python -m pip install --upgrade pip setuptools wheel

echo "=== Установка зависимостей ==="
if [ -f "requirements.txt" ]; then
    python -m pip install -r requirements.txt
else
    echo "⚠️  Файл requirements.txt не найден — шаг пропущен."
fi

echo ""
echo "✅ Готово! Окружение настроено: $(pwd)/.venv"
echo "   Запустить проект: ./start.sh"