from __future__ import annotations

import logging
from datetime import datetime

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from .config import AppConfig

logger = logging.getLogger(__name__)


class InfluxLatencyWriter:
    def __init__(self, *, url: str, token: str, org: str, bucket: str) -> None:
        self._org = org
        self._bucket = bucket
        self._client = InfluxDBClient(url=url, token=token, org=org, timeout=5_000)
        self._write_api = self._client.write_api(write_options=SYNCHRONOUS)

    @classmethod
    def from_config(cls, config: AppConfig) -> "InfluxLatencyWriter | None":
        if not config.influxdb_enabled:
            return None

        required_values = {
            "INFLUXDB_URL": config.influxdb_url,
            "INFLUXDB_TOKEN": config.influxdb_token,
            "INFLUXDB_ORG": config.influxdb_org,
            "INFLUXDB_BUCKET": config.influxdb_bucket,
        }
        missing = [name for name, value in required_values.items() if not value]
        if missing:
            raise ValueError(
                "InfluxDB is enabled but the following variables are missing: "
                + ", ".join(missing)
            )

        return cls(
            url=config.influxdb_url or "",
            token=config.influxdb_token or "",
            org=config.influxdb_org or "",
            bucket=config.influxdb_bucket or "",
        )

    def write_market_data_latency(
        self,
        *,
        symbol: str,
        channel: str,
        topic: str,
        message_type: str,
        bridge_processing_ms: float,
        source_event_latency_ms: float | None,
        received_at: datetime,
    ) -> None:
        try:
            point = (
                Point("market_data_latency")
                .tag("source", "kraken")
                .tag("symbol", symbol)
                .tag("channel", channel)
                .tag("topic", topic)
                .tag("message_type", message_type)
                .field("bridge_processing_ms", float(bridge_processing_ms))
                .time(received_at, WritePrecision.MS)
            )
            if source_event_latency_ms is not None:
                point = point.field("source_event_latency_ms", float(source_event_latency_ms))

            self._write_api.write(bucket=self._bucket, org=self._org, record=point)
        except Exception as exc:
            logger.warning("Failed to write latency point to InfluxDB: %s", exc)

    def close(self) -> None:
        self._client.close()
