#!/usr/bin/env bash

if [ ! -d ".venv" ]; then
    ./install.sh
fi

echo "=== Запуск проекта на Python 3.13 ==="
export NIXPKGS_ALLOW_UNFREE=1

nix-shell -p steam-run pkgs.python313 --run "steam-run bash -c '
  source .venv/bin/activate && \
  python main.py
'"
