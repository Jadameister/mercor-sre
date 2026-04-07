from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv


@dataclass(slots=True)
class AppConfig:
    kraken_ws_url: str
    kafka_bootstrap_servers: str
    kafka_topic: str
    kraken_channel: str
    kraken_symbols: list[str]
    kraken_book_depth: int
    log_level: str
    log_json_path: str | None
    kafka_security_protocol: str | None
    kafka_sasl_mechanism: str | None
    kafka_sasl_username: str | None
    kafka_sasl_password: str | None
    influxdb_enabled: bool
    influxdb_url: str | None
    influxdb_token: str | None
    influxdb_org: str | None
    influxdb_bucket: str | None

    @classmethod
    def from_env(cls) -> "AppConfig":
        load_dotenv()

        symbols_raw = os.getenv("KRAKEN_SYMBOLS", "BTC/USD")
        symbols = [item.strip() for item in symbols_raw.split(",") if item.strip()]
        if not symbols:
            raise ValueError("KRAKEN_SYMBOLS must contain at least one symbol")

        channel = os.getenv("KRAKEN_CHANNEL", "ticker").strip().lower()
        if channel not in {"ticker", "book"}:
            raise ValueError("KRAKEN_CHANNEL must be either 'ticker' or 'book'")

        influxdb_enabled = os.getenv("INFLUXDB_ENABLED", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        return cls(
            kraken_ws_url=os.getenv("KRAKEN_WS_URL", "wss://ws.kraken.com/v2"),
            kafka_bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
            kafka_topic=os.getenv("KAFKA_TOPIC", "kraken-market-data"),
            kraken_channel=channel,
            kraken_symbols=symbols,
            kraken_book_depth=int(os.getenv("KRAKEN_BOOK_DEPTH", "10")),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            log_json_path=os.getenv("LOG_JSON_PATH") or None,
            kafka_security_protocol=os.getenv("KAFKA_SECURITY_PROTOCOL") or None,
            kafka_sasl_mechanism=os.getenv("KAFKA_SASL_MECHANISM") or None,
            kafka_sasl_username=os.getenv("KAFKA_SASL_USERNAME") or None,
            kafka_sasl_password=os.getenv("KAFKA_SASL_PASSWORD") or None,
            influxdb_enabled=influxdb_enabled,
            influxdb_url=os.getenv("INFLUXDB_URL") or None,
            influxdb_token=os.getenv("INFLUXDB_TOKEN") or None,
            influxdb_org=os.getenv("INFLUXDB_ORG") or None,
            influxdb_bucket=os.getenv("INFLUXDB_BUCKET") or None,
        )

    def kafka_config(self) -> dict[str, Any]:
        config: dict[str, Any] = {
            "bootstrap.servers": self.kafka_bootstrap_servers,
            "client.id": "kraken-kafka-bridge",
        }

        if self.kafka_security_protocol:
            config["security.protocol"] = self.kafka_security_protocol
        if self.kafka_sasl_mechanism:
            config["sasl.mechanism"] = self.kafka_sasl_mechanism
        if self.kafka_sasl_username:
            config["sasl.username"] = self.kafka_sasl_username
        if self.kafka_sasl_password:
            config["sasl.password"] = self.kafka_sasl_password

        return config
