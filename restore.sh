#!/usr/bin/env bash
# restore.sh — восстановление из датированного снимка.
#
#   ./restore.sh                       # последний снимок (БД + файлы + .env)
#   ./restore.sh db                    # последний снимок — только БД
#   ./restore.sh files                 # последний снимок — только файлы
#   ./restore.sh env                   # последний снимок — только .env
#   ./restore.sh 2026-10-21-1726       # конкретный снимок, всё
#   ./restore.sh 2026-10-21-1726 db    # конкретный снимок, только БД
#
# Перезаписывает текущее состояние. Спрашивает подтверждение.
set -e

cd "$(dirname "$0")"

BACKUP_DIR="$HOME/backups"

# --- Разбор аргументов ---
SNAPSHOT=""
KIND="all"

for arg in "$@"; do
    case "$arg" in
        db|files|env|all) KIND="$arg" ;;
        [0-9]*-*-*-*)
            if [ -d "$BACKUP_DIR/$arg" ]; then
                SNAPSHOT="$BACKUP_DIR/$arg"
            else
                echo "❌ Снимок не найден: $BACKUP_DIR/$arg" >&2
                exit 1
            fi
            ;;
        *)
            echo "❌ Неизвестный аргумент: $arg" >&2
            echo "   Использование: $0 [SNAPSHOT] [db|files|env|all]" >&2
            exit 1
            ;;
    esac
done

# --- Если снимок не указан — берём последний ---
if [ -z "$SNAPSHOT" ]; then
    SNAPSHOT=$(ls -1d "$BACKUP_DIR"/[0-9]*-*-*-* 2>/dev/null | sort | tail -1)
    if [ -z "$SNAPSHOT" ]; then
        echo "❌ В $BACKUP_DIR нет снимков." >&2
        exit 1
    fi
fi

STAMP=$(basename "$SNAPSHOT")

echo "Восстановление из: $SNAPSHOT"
echo "Тип: $KIND"
echo ""

echo "⚠️  Это перезапишет текущее состояние ($KIND)."
read -r -p "Продолжить? [y/N] " confirm
[ "$confirm" = "y" ] || { echo "Отменено."; exit 1; }

# --- DB_URL для восстановления БД ---
if [ "$KIND" = "all" ] || [ "$KIND" = "db" ]; then
    if [ ! -f ".env" ]; then
        echo "❌ .env не найден — не могу восстановить БД." >&2
        exit 1
    fi
    DB_URL=$(grep -E '^DATABASE_URL=' .env | head -n1 | cut -d= -f2- | sed 's/^"//;s/"$//')
    DB_URL="${DB_URL/postgresql+psycopg:\/\//postgresql:\/\/}"
    DB_URL="${DB_URL/postgresql+psycopg2:\/\//postgresql:\/\/}"
fi

# --- Восстановление БД ---
if [ "$KIND" = "all" ] || [ "$KIND" = "db" ]; then
    if [ ! -f "$SNAPSHOT/db.sql" ]; then
        echo "❌ $SNAPSHOT/db.sql не найден." >&2
        exit 1
    fi
    echo "→ Восстанавливаю БД (--clean --if-exists)..."
    if ! psql "$DB_URL" < "$SNAPSHOT/db.sql" > /tmp/avelea_restore.log 2>&1; then
        echo "❌ psql упал. Лог: /tmp/avelea_restore.log" >&2
        tail -20 /tmp/avelea_restore.log
        exit 1
    fi
    echo "  ✅ БД восстановлена"
fi

# --- Восстановление файлов ---
if [ "$KIND" = "all" ] || [ "$KIND" = "files" ]; then
    echo "→ Восстанавливаю файлы..."

    if [ -d "$SNAPSHOT/uploads" ]; then
        rm -rf static/uploads
        mkdir -p static/uploads
        cp -a "$SNAPSHOT/uploads/." static/uploads/
        echo "  ✅ static/uploads/ ($(find static/uploads -type f | wc -l) файлов)"
    fi

    if [ -d "$SNAPSHOT/site" ]; then
        rm -rf static/site
        mkdir -p static/site
        cp -a "$SNAPSHOT/site/." static/site/
        echo "  ✅ static/site/ ($(find static/site -type f | wc -l) файлов)"
    fi
fi

# --- Восстановление .env ---
if [ "$KIND" = "env" ]; then
    if [ -f "$SNAPSHOT/env" ]; then
        echo "→ Восстанавливаю .env..."
        if [ -f ".env" ]; then
            cp .env ".env.before-restore-$(date +%s)"
            echo "  (текущий .env сохранён как .env.before-restore-*)"
        fi
        cp "$SNAPSHOT/env" .env
        echo "  ✅ .env восстановлен"
    fi
fi

echo ""
echo "✅ Готово. Перезапусти сервер: Ctrl+C + ./start.sh"