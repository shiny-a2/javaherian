#!/usr/bin/env bash
# Usage: TELEGRAM_BOT_TOKEN=... SERVICE_URL=... ./set_webhook.sh
set -euo pipefail
: "${TELEGRAM_BOT_TOKEN:?Missing TELEGRAM_BOT_TOKEN}"
: "${SERVICE_URL:?Missing SERVICE_URL}"

echo "Setting webhook to: ${SERVICE_URL}/telegram/webhook"
curl -sS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  -d "url=${SERVICE_URL}/telegram/webhook" | jq .
echo "Done."
