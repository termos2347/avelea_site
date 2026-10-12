#!/usr/bin/env bash
# backup.sh — бэкап БД и файлов проекта.
#
# Запуск:  ./backup.sh
#
# Делает два файла в ~/backups/ с таймстампом:
#   db-YYYY-MM-DD-HHMM.sql         — дамп Postgres
#   uploads-YYYY-MM-DD-HHMM.tar.gz — картинки + .env
#
# Хранит последние 10 пар. Всё старше — удаляется при запуске.
set -e

cd "$(dirname "$0")"

BACKUP_DIR="$HOME/backups"
KEEP=10
STAMP=$(date +%F-%H%M)

mkdir -p "$BACKUP_DIR"

# --- 1. DATABASE_URL из .env ---
if [ ! -f ".env" ]; then
    echo "❌ .env не найден в $(pwd)" >&2
    exit 1
fi

DB_URL=$(grep -E '^DATABASE_URL=' .env | head -n1 | cut -d= -f2- | sed 's/^"//;s/"$//')

if [ -z "$DB_URL" ]; then
    echo "❌ DATABASE_URL не найден в .env" >&2
    exit 1
fi

# SQLAlchemy-формат → нативный для pg_dump
DB_URL="${DB_URL/postgresql+psycopg:\/\//postgresql:\/\/}"
DB_URL="${DB_URL/postgresql+psycopg2:\/\//postgresql:\/\/}"

# --- 2. Дамп БД ---
DB_FILE="$BACKUP_DIR/db-$STAMP.sql"
echo "→ Бэкап БД → $DB_FILE"

if ! pg_dump "$DB_URL" > "$DB_FILE"; then
    echo "❌ pg_dump упал. Бэкап БД не сделан." >&2
    rm -f "$DB_FILE"
    exit 1
fi

# --- 3. Архив файлов ---
FILES_FILE="$BACKUP_DIR/uploads-$STAMP.tar.gz"
echo "→ Бэкап файлов → $FILES_FILE"

tar czf "$FILES_FILE" static/uploads/ .env

# --- 4. Оставляем последние $KEEP пар ---
echo "→ Оставляю последние $KEEP бэкапов, старые удаляю..."

# Для каждого префикса отдельно: сортируем по времени (новые сверху),
# всё за пределами первых $KEEP — удаляем.
for PREFIX in db uploads; do
    mapfile -t FILES < <(ls -1t "$BACKUP_DIR"/${PREFIX}-* 2>/dev/null || true)
    for ((i = KEEP; i < ${#FILES[@]}; i++)); do
        rm -f "${FILES[$i]}"
    done
done

# --- 5. Отчёт ---
echo ""
echo "✅ Готово. Содержимое $BACKUP_DIR:"
echo ""
ls -lh "$BACKUP_DIR/" | grep -E 'db-|uploads-|total|итого'
echo ""
echo "Восстановление:"
echo "  БД:     psql \"<DATABASE_URL без +psycopg>\" < $DB_FILE"
echo "  Файлы:  tar xzf $FILES_FILE -C $(pwd)"