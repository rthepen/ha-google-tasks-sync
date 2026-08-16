#!/usr/bin/with-contenv bashio

bashio::log.info "Starting Google Tasks Multi-Account Sync Add-on..."

# Ensure data directory exists
mkdir -p /data/tokens
mkdir -p /data/backup

# Copy initial client_secret if provided in /data or fallback
if [ -f /data/client_secret.json ]; then
    bashio::log.info "Found client_secret.json in /data"
fi

# Run the FastAPI application
cd /app
exec uvicorn main:app --host 0.0.0.0 --port 8099 --proxy-headers
