#!/usr/bin/env bash
# Поднять/обновить compose-проект rf-analytics после rsync deploy/ → /opt/rf-analytics.
# Запуск из Actions: ssh … "bash -s" < deploy/stack-up.sh
# Трогает только свой проект; edge-caddy не перезапускается никогда (AGENTS.md).
set -euo pipefail
cd /opt/rf-analytics
install -d -m 755 raw marts static
docker compose -p rf-analytics -f docker-compose.yml config -q
docker compose -p rf-analytics -f docker-compose.yml up -d --remove-orphans
# Caddyfile смонтирован файлом, admin off: изменения подхватываются только перезапуском своего caddy.
if [[ "${CADDY_CHANGED:-0}" == "1" ]]; then
  docker compose -p rf-analytics -f docker-compose.yml restart caddy
fi
docker compose -p rf-analytics -f docker-compose.yml ps --format '{{.Name}} {{.Status}}'
# Старые образы api (только свои теги): оставляем current и только что выложенный.
if [[ -n "${API_TAG:-}" ]]; then
  docker images rf-analytics-api --format '{{.Tag}}' | grep -vx -e current -e "$API_TAG" \
    | sed 's/^/rf-analytics-api:/' | xargs -r docker rmi > /dev/null 2>&1 || true
fi
