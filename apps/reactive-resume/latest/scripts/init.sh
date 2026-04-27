#!/bin/bash

# Generated from official installation evidence:
# - https://github.com/AmruthPillai/Reactive-Resume/blob/main/compose.yml
# - https://github.com/AmruthPillai/Reactive-Resume/blob/main/.env.example

set -eu

random_hex() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex 32
    else
        tr -dc 'a-f0-9' </dev/urandom | head -c 64
    fi
}

if [ ! -f .env ]; then
    postgres_password="$(random_hex)"
    browserless_token="$(random_hex)"
    auth_secret="$(random_hex)"

    umask 077
    cat > .env <<EOF
TZ=Asia/Shanghai
NODE_ENV=production
APP_URL=http://localhost:3000
PRINTER_APP_URL=http://reactive-resume:3000
PRINTER_ENDPOINT=ws://printer:3000?token=${browserless_token}
DATABASE_URL=postgresql://postgres:${postgres_password}@postgres:5432/postgres
AUTH_SECRET=${auth_secret}
POSTGRES_DB=postgres
POSTGRES_USER=postgres
POSTGRES_PASSWORD=${postgres_password}
QUEUED=10
HEALTH=true
CONCURRENT=5
TOKEN=${browserless_token}
EOF
fi
