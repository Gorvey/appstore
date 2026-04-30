#!/bin/bash

# Generated from official installation evidence:
# - https://github.com/kittors/CliRelay/blob/v6.8.32/install.sh

mkdir -p auths logs data
rand_hex() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex "$1"
    else
        head -c "$1" /dev/urandom | od -An -tx1 | tr -d ' \n'
    fi
}

if [ ! -f config.yaml ]; then
    CLIRELAY_SECRET="$(rand_hex 16)"
    CLIRELAY_API_KEY="sk-$(rand_hex 16)"
    cat > config.yaml <<EOF
# CliRelay configuration file - generated during 1Panel installation
host: ""
port: 8317

redis:
  enable: false

remote-management:
  allow-remote: true
  secret-key: "${CLIRELAY_SECRET}"
  disable-control-panel: false

auth-dir: "/root/.cli-proxy-api"

api-keys:
  - "${CLIRELAY_API_KEY}"

debug: false
logging-to-file: true
logs-max-total-size-mb: 100
usage-statistics-enabled: true
request-retry: 3
max-retry-interval: 30
routing:
  strategy: "round-robin"
EOF
fi
