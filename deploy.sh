#!/usr/bin/env bash
# Deploy TGParaletClubBot to remote server via rsync + docker compose
# Usage: ./deploy.sh
# Server: SD-sportdom01-sel (from ~/.ssh/config), path: /srv/docker/TGParaletClubBot

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load from .env if present (do not export .env to remote)
if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

DEPLOY_HOST="${DEPLOY_HOST:-SD-sportdom01-sel}"
DEPLOY_PATH="${DEPLOY_PATH:-/srv/docker/TGParaletClubBot}"
echo "Deploying to $DEPLOY_HOST:$DEPLOY_PATH"

# Rsync: код и конфиги, без секретов и локальных данных
rsync -avz --delete \
  --exclude='.env' \
  --exclude='.git' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.DS_Store' \
  --exclude='venv/' \
  --exclude='.venv/' \
  --exclude='*.db' \
  --exclude='*.sqlite*' \
  --exclude='.idea/' \
  --exclude='.cursor/' \
  --exclude='cache/' \
  --exclude='debug_*.html' \
  . "$DEPLOY_HOST:$DEPLOY_PATH"

# На сервере: создать .env из примера при отсутствии, затем сборка и запуск
ssh "$DEPLOY_HOST" "cd $DEPLOY_PATH && (test -f .env || { cp .env.example .env && echo 'Created .env from .env.example — edit with real TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID'; }) && docker compose build && docker compose up -d"

echo "Done. If .env was created from example, edit on server: ssh $DEPLOY_HOST \"nano $DEPLOY_PATH/.env\""
