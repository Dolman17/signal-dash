#!/usr/bin/env bash
set -e

echo "Starting SignalDash container..."

mkdir -p "${SIGNALDASH_STORAGE_ROOT:-/srv/signaldash/storage}"
mkdir -p "${SIGNALDASH_INGEST_ROOT:-/srv/signaldash/ingest}"
mkdir -p "${SIGNALDASH_BACKUP_ROOT:-/srv/signaldash/backups}"
mkdir -p "${SIGNALDASH_LOG_ROOT:-/srv/signaldash/logs}"

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  echo "Running database migrations..."
  flask db upgrade
fi

echo "Starting process: $*"
exec "$@"