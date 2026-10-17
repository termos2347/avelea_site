#!/usr/bin/env bash
# clean.sh — очистка мусора в проекте.
#
# Без флагов: удаляет регенерируемый мусор (кэши, .pyc, IDE-файлы).
# С флагом --init: ДОПОЛНИТЕЛЬНО удаляет пустые __init__.py
#                  (файлы с кодом/комментариями НЕ трогаются).
#
# Использование:
#   ./clean.sh           # только кэш и мусор
#   ./clean.sh --init    # + пустые __init__.py (с подтверждением)
#   ./clean.sh --init -y # + пустые __init__.py без подтверждения
set -e

cd "$(dirname "$0")"

REMOVE_INIT=0
ASSUME_YES=0

for arg in "$@"; do
    case "$arg" in
        --init)    REMOVE_INIT=1 ;;
        -y|--yes)  ASSUME_YES=1 ;;
        -h|--help)
            cat <<EOF
Использование: $0 [--init] [-y]

  --init   удалить пустые __init__.py (с подтверждением)
  -y       не спрашивать подтверждения (для --init)
EOF
            exit 0
            ;;
        *)
            echo "Неизвестный аргумент: $arg" >&2
            exit 1
            ;;
    esac
done

EXCLUDES=(
    -not -path "./.venv/*"
    -not -path "./.git/*"
    -not -path "./node_modules/*"
)

# Счётчик удалённых пустых __init__.py
INIT_REMOVED=0

# ============================================================
# ЧАСТЬ 1: сгенерированный мусор (всегда)
# ============================================================

echo "=== Мусор до очистки ==="

PYCACHE=$(find . -type d -name "__pycache__" "${EXCLUDES[@]}" 2>/dev/null | wc -l)
PYC=$(find . -type f -name "*.pyc" "${EXCLUDES[@]}" 2>/dev/null | wc -l)
PYO=$(find . -type f -name "*.pyo" "${EXCLUDES[@]}" 2>/dev/null | wc -l)
PYTEST=$(find . -type d -name ".pytest_cache" "${EXCLUDES[@]}" 2>/dev/null | wc -l)
DS=$(find . -type f -name ".DS_Store" "${EXCLUDES[@]}" 2>/dev/null | wc -l)
SWP=$(find . -type f -name "*.swp" "${EXCLUDES[@]}" 2>/dev/null | wc -l)

echo "  __pycache__/     : $PYCACHE папок"
echo "  *.pyc            : $PYC файлов"
echo "  *.pyo            : $PYO файлов"
echo "  .pytest_cache/   : $PYTEST папок"
echo "  .DS_Store        : $DS файлов"
echo "  *.swp            : $SWP файлов"

TOTAL=$((PYCACHE + PYC + PYO + PYTEST + DS + SWP))

echo ""
echo "=== Очистка ==="

if [ "$TOTAL" -eq 0 ]; then
    echo "→ Мусора нет, всё чисто."
else
    find . -type d -name "__pycache__" "${EXCLUDES[@]}" -exec rm -rf {} + 2>/dev/null || true
    find . -type f \( -name "*.pyc" -o -name "*.pyo" \) "${EXCLUDES[@]}" -delete 2>/dev/null || true
    find . -type d \( -name ".pytest_cache" -o -name ".mypy_cache" -o -name ".ruff_cache" \) "${EXCLUDES[@]}" -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name ".DS_Store" "${EXCLUDES[@]}" -delete 2>/dev/null || true
    find . -type d \( -name ".idea" -o -name ".vscode" \) "${EXCLUDES[@]}" -exec rm -rf {} + 2>/dev/null || true
    find . -type f \( -name "*.swp" -o -name "*.swo" -o -name "*~" -o -name ".#*" \) "${EXCLUDES[@]}" -delete 2>/dev/null || true
    echo "✅ Сгенерированный мусор удалён."
fi

# ============================================================
# ЧАСТЬ 2: пустые __init__.py
# ============================================================

echo ""
echo "=== Пустые __init__.py ==="

mapfile -t ALL_INITS < <(
    find . -type f -name "__init__.py" "${EXCLUDES[@]}" | sort
)

EMPTY=()
for f in "${ALL_INITS[@]}"; do
    if [ ! -s "$f" ] || [ -z "$(tr -d '[:space:]' < "$f")" ]; then
        EMPTY+=("$f")
    fi
done

TOTAL_INITS=${#ALL_INITS[@]}
TOTAL_EMPTY=${#EMPTY[@]}

echo "  Всего __init__.py:   $TOTAL_INITS"
echo "  Пустых:              $TOTAL_EMPTY"

if [ "$TOTAL_EMPTY" -eq 0 ]; then
    echo "→ Удалять нечего."
elif [ "$REMOVE_INIT" -eq 0 ]; then
    echo ""
    echo "ℹ️  Пустые __init__.py остались (не удаляем без --init)."
    echo "   Запусти: ./clean.sh --init"
else
    echo ""
    echo "Будут удалены:"
    for f in "${EMPTY[@]}"; do
        echo "  $f"
    done
    echo ""

    if [ "$ASSUME_YES" -eq 0 ]; then
        read -p "Удалить эти файлы? [y/N]: " confirm
        if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
            echo "→ Отмена."
            TOTAL_EMPTY=0
        fi
    fi

    if [ "$TOTAL_EMPTY" -gt 0 ]; then
        for f in "${EMPTY[@]}"; do
            rm -f "$f"
            INIT_REMOVED=$((INIT_REMOVED + 1))
        done
        echo "✅ Удалено пустых __init__.py: $INIT_REMOVED"
        echo "   Осталось __init__.py: $(( TOTAL_INITS - INIT_REMOVED ))"
    fi
fi

# ============================================================
# Итог
# ============================================================

echo ""
echo "============================================================"
echo "ИТОГО:"
echo "  Мусора удалено:            $(( PYCACHE + PYC + PYO + PYTEST + DS + SWP )) объектов"
echo "  Пустых __init__.py удалено: $INIT_REMOVED"
AFTER=$(find . -type f "${EXCLUDES[@]}" | wc -l)
echo "  Файлов в проекте сейчас:   $AFTER"
echo "============================================================"