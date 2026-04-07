#!/usr/bin/env bash
set -euo pipefail

if [[ "${ENABLE_ES_SYNTHETIC_BACKFILL:-true}" == "true" ]]; then
  python3 /opt/data-generator/elasticsearch_exporter_generator.py --backfill-only
fi

if [[ "${ENABLE_KAFKA_SYNTHETIC_BACKFILL:-true}" == "true" ]]; then
  python3 /opt/data-generator/kafka_exporter_generator.py --backfill-only
fi

exec /usr/local/bin/prometheus \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/prometheus \
  --web.enable-lifecycle
