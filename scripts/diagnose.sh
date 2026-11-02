#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "\${BASH_SOURCE[0]}")/.."
compose=(docker compose --env-file .env.preview -f docker-compose.preview.yml)
"\${compose[@]}" ps
"\${compose[@]}" logs --tail=35 api worker proxy
curl -fsS http://127.0.0.1:18512/api/v1/health
