#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_FILE="$SCRIPT_DIR/app.py"
INIT_SQL="$PROJECT_ROOT/init/FG.sql"

MODE="${1:-all}"

if [[ "$MODE" != "all" && "$MODE" != "backend" && "$MODE" != "db" ]]; then
  echo "Usage: ./application/start.sh [all|backend|db]"
  echo "  all: init DB (optional CSV) + start backend (default)"
  echo "  backend: start backend only"
  echo "  db: init DB only"
  exit 1
fi

ensure_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1"
    exit 1
  fi
}

configure_db_env() {
  export DB_USER="${DB_USER:-$USER}"
  export DB_PASSWORD="${DB_PASSWORD:-}"
  export DB_HOST="${DB_HOST:-/var/run/postgresql}"
  export DB_PORT="${DB_PORT:-5432}"
  export DB_NAME="${DB_NAME:-fgdb}"
}

configure_app_env() {
  export APP_HOST="${APP_HOST:-0.0.0.0}"
  export APP_PORT="${APP_PORT:-5000}"
  export APP_DEBUG="${APP_DEBUG:-true}"
}

init_db() {
  ensure_command sudo
  ensure_command psql
  ensure_command createuser
  ensure_command createdb

  echo "[1/3] Initializing PostgreSQL objects..."

  if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${USER}'" | grep -q 1; then
    echo "Role '${USER}' already exists."
  else
    sudo -u postgres createuser "${USER}"
    echo "Role '${USER}' created."
  fi

  sudo -u postgres createdb fgdb 2>/dev/null || true
  if [[ ! -r "$INIT_SQL" ]]; then
    echo "Cannot read SQL file: $INIT_SQL"
    exit 1
  fi
  # Read SQL as current user and pipe to postgres psql to avoid home directory permission issues.
  cat "$INIT_SQL" | sudo -u postgres psql -d fgdb

  echo "Database schema ready."
}

load_csv_if_needed() {
  local load_csv_value="${LOAD_CSV:-true}"
  local load_csv_normalized
  load_csv_normalized="$(printf '%s' "$load_csv_value" | tr '[:upper:]' '[:lower:]')"

  if [[ "$load_csv_normalized" == "false" || "$load_csv_normalized" == "0" || "$load_csv_normalized" == "no" ]]; then
    echo "[2/3] LOAD_CSV=${load_csv_value}; skipping CSV loading."
  else
    echo "[2/3] LOAD_CSV=${load_csv_value}; loading CSV data..."
    python3 "$SCRIPT_DIR/load_csv.py"
  fi
}

start_backend() {
  configure_db_env
  configure_app_env

  echo "[3/3] Starting backend + frontend pages (Flask unified app)..."
  echo "URL: http://127.0.0.1:${APP_PORT}/"
  echo "Tree Preview: http://127.0.0.1:${APP_PORT}/tree-preview"

  python3 "$APP_FILE"
}

cd "$PROJECT_ROOT"

if [[ "$MODE" == "db" ]]; then
  configure_db_env
  init_db
  load_csv_if_needed
  echo "Database init completed."
  exit 0
fi

if [[ "$MODE" == "all" ]]; then
  configure_db_env
  init_db
  load_csv_if_needed
fi

start_backend
