#!/bin/bash
# Initialize InfluxDB 2.x via the HTTP API (no influx CLI required).
# Supervisord runs this once after influxd starts (autorestart=false).
set -e

INFLUX_URL="${INFLUX_URL:-http://localhost:8086}"
INFLUX_USERNAME="${INFLUX_USERNAME:-admin}"
INFLUX_PASSWORD="${INFLUX_PASSWORD:-admin12345}"
INFLUX_ORG="${INFLUX_ORG:-test-org}"
INFLUX_BUCKET="${INFLUX_BUCKET:-marketdata}"
INFLUX_TOKEN="${INFLUX_TOKEN:-marketdata-token}"

echo "[influx-init] Waiting for InfluxDB to be ready..."
until curl -sf -o /dev/null "${INFLUX_URL}/ping"; do
    sleep 2
done
echo "[influx-init] InfluxDB is up"

# If the configured token can already read the target bucket list, initialization is done.
if curl -sf -H "Authorization: Token ${INFLUX_TOKEN}" \
    "${INFLUX_URL}/api/v2/buckets?org=${INFLUX_ORG}" > /dev/null; then
    echo "[influx-init] Configured token already has bucket access, skipping"
    exit 0
fi

SETUP_RESPONSE=$(curl -s "${INFLUX_URL}/api/v2/setup")
if echo "$SETUP_RESPONSE" | grep -Eq '"allowed"[[:space:]]*:[[:space:]]*true'; then
    echo "[influx-init] Running initial setup..."
    curl -s -X POST "${INFLUX_URL}/api/v2/setup" \
        -H 'Content-Type: application/json' \
        -d "{
            \"username\": \"${INFLUX_USERNAME}\",
            \"password\": \"${INFLUX_PASSWORD}\",
            \"org\": \"${INFLUX_ORG}\",
            \"bucket\": \"${INFLUX_BUCKET}\",
            \"token\": \"${INFLUX_TOKEN}\"
        }" > /dev/null
    echo "[influx-init] Setup complete. org=${INFLUX_ORG} bucket=${INFLUX_BUCKET} token=${INFLUX_TOKEN}"
    exit 0
fi

echo "[influx-init] Instance is already initialized, but configured token cannot read buckets"
echo "[influx-init] Expected token=${INFLUX_TOKEN} org=${INFLUX_ORG} bucket=${INFLUX_BUCKET}"
exit 1
