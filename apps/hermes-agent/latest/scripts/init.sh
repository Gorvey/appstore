#!/bin/bash

# Generated from official installation evidence:
# - https://github.com/NousResearch/hermes-agent/blob/main/docker/entrypoint.sh
# - https://github.com/NousResearch/hermes-agent/blob/main/.env.example
# - https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/docker.md
# - https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/messaging/open-webui.md

set -eu

mkdir -p data

if [ ! -f data/.env ]; then
    umask 077
    cat > data/.env <<'EOF'
# Hermes Agent defaults for Open WebUI integration.
API_SERVER_ENABLED=true
API_SERVER_HOST=0.0.0.0
API_SERVER_PORT=8642
API_SERVER_KEY=change-me-hermes-key
API_SERVER_MODEL_NAME=hermes-agent

# Add or edit any other Hermes environment variables below.
# Full reference:
# https://hermes-agent.nousresearch.com/docs/reference/environment-variables

# Example provider settings:
# OPENROUTER_API_KEY=
# GOOGLE_API_KEY=
# OPENAI_API_KEY=
# OPENAI_BASE_URL=
EOF
fi
