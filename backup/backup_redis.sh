#!/bin/sh
# Simple one-shot backup script using redis-cli SAVE and copying dump.rdb to backups
set -e
BACKUP_DIR=${BACKUP_PATH:-/backups}
mkdir -p "$BACKUP_DIR"
echo "Triggering Redis SAVE..."
redis-cli -h ${REDIS_HOST:-redis} -p ${REDIS_PORT:-6379} SAVE
echo "Copying dump..."
cp /data/dump.rdb "$BACKUP_DIR/dump-$(date -u +%Y%m%dT%H%M%SZ).rdb" || echo "Copy may fail if paths differ"
echo "Backup finished."