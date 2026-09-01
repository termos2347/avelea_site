#!/usr/bin/env bash
set -e

echo "=== Сносим старое окружение ==="
rm -rf .venv

echo "=== Создаем новое окружение на базе Python 3.13 ==="
export NIXPKGS_ALLOW_UNFREE=1

# Запускаем сборку, явно подсунув python313 из nixpkgs
nix-shell -p steam-run pkgs.python313 --run "steam-run bash -c '
  python3.13 -m venv .venv && \
  source .venv/bin/activate && \
  pip install --upgrade pip && \
  pip install -r requirements.txt
'"

echo "=== Готово! Все библиотеки успешно установлены ==="
