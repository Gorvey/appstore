#!/bin/sh

# Generated from official installation evidence:
# - ./change-api/Dockerfile (the bundled service defines UID/GID 10001)
set -eu

mkdir -p change-api-data
chown -R 10001:10001 change-api-data
