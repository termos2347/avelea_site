#!/usr/bin/env bash
# backup.sh — бэкап БД и файлов проекта в датированную папку.
#
# Запуск:  ./backup.sh
#
# Структура:
#   ~/backups/
#   ├── 2026-10-21-1726/
#   │   ├── db.sql       — дамп Postgres (с --clean --if-exists)
#   │   ├── env          — копия .env
#   │   ├── uploads/     — static/uploads/* как есть
#   │   └── site/        — static/site/* как есть
#   └── 2026-10-21-1756/
#       └── ...
#
# Хранит последние $KEEP снимков. Всё старше — удаляется.
set -e

cd "$(dirname "$0")"

BACKUP_DIR="$HOME/backups"
KEEP=48              # 48 снимков × 30 мин = сутки истории
STAMP=$(date +%F-%H%M)

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

# --- 2. Создаём папку снимка ---
SNAPSHOT="$BACKUP_DIR/$STAMP"

if [ -d "$SNAPSHOT" ]; then
    echo "❌ Папка $SNAPSHOT уже существует (два запуска в одну минуту?)" >&2
    exit 1
fi

mkdir -p "$SNAPSHOT/uploads" "$SNAPSHOT/site"

echo "→ Снимок → $SNAPSHOT"

# --- 3. Дамп БД ---
echo "  • БД"
if ! pg_dump --clean --if-exists --no-owner --no-acl "$DB_URL" > "$SNAPSHOT/db.sql"; then    echo "❌ pg_dump упал. Бэкап прерван." >&2
    rm -rf "$SNAPSHOT"
    exit 1
fi

# --- 4. Копия .env ---
echo "  • .env"
cp .env "$SNAPSHOT/env"

# --- 5. Файлы — копируем как есть ---
echo "  • uploads/"
if [ -d static/uploads ]; then
    cp -a static/uploads/. "$SNAPSHOT/uploads/"
fi

echo "  • site/"
if [ -d static/site ]; then
    cp -a static/site/. "$SNAPSHOT/site/"
fi

# --- 6. Удаляем старые снимки ---
echo "→ Оставляю $KEEP последних, старые удаляю..."

# Формат имени YYYY-MM-DD-HHMM → лексикографическая сортировка = хронология.
mapfile -t SNAPSHOTS < <(ls -1d "$BACKUP_DIR"/[0-9]*-*-*-* 2>/dev/null | sort)

TOTAL=${#SNAPSHOTS[@]}
if [ "$TOTAL" -gt "$KEEP" ]; then
    TO_DELETE=$((TOTAL - KEEP))
    for ((i = 0; i < TO_DELETE; i++)); do
        rm -rf "${SNAPSHOTS[$i]}"
    done
    echo "  Удалено старых: $TO_DELETE"
fi

# --- 7. Отчёт ---
SIZE=$(du -sh "$SNAPSHOT" | cut -f1)
DB_SIZE=$(du -h "$SNAPSHOT/db.sql" | cut -f1)
UPLOADS_N=$(find "$SNAPSHOT/uploads" -type f 2>/dev/null | wc -l)
SITE_N=$(find "$SNAPSHOT/site" -type f 2>/dev/null | wc -l)

echo ""
echo "✅ Готово. Снимок: $SNAPSHOT"
echo "   Размер снимка:  $SIZE"
echo "   БД:             $DB_SIZE"
echo "   uploads/:       $UPLOADS_N файлов"
echo "   site/:          $SITE_N файлов"
echo ""
echo "Всего снимков: $(ls -1d "$BACKUP_DIR"/[0-9]*-*-*-* 2>/dev/null | wc -l) (KEEP=$KEEP)"
echo ""
echo "Восстановление:"
echo "  ./restore.sh                    # последний снимок, всё"
echo "  ./restore.sh $STAMP             # конкретный снимок, всё"
echo "  ./restore.sh $STAMP db          # только БД"
echo "  ./restore.sh $STAMP files       # только файлы"