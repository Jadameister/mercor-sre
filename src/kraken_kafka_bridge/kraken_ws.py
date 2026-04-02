from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

import websockets
from websockets.client import WebSocketClientProtocol

from .config import AppConfig
from .influx_writer import InfluxLatencyWriter
from .kafka_producer import KafkaMarketDataProducer

logger = logging.getLogger(__name__)


class KrakenKafkaBridge:
    def __init__(
        self,
        config: AppConfig,
        producer: KafkaMarketDataProducer,
        influx_writer: InfluxLatencyWriter | None = None,
    ) -> None:
        self.config = config
        self.producer = producer
        self.influx_writer = influx_writer
        self._max_backoff_seconds = 30

    def build_subscribe_message(self) -> dict[str, Any]:
        if self.config.kraken_channel == "ticker":
            return {
                "method": "subscribe",
                "params": {
                    "channel": "ticker",
                    "symbol": self.config.kraken_symbols,
                    "snapshot": True,
                },
            }

        return {
            "method": "subscribe",
            "params": {
                "channel": "book",
                "symbol": self.config.kraken_symbols,
                "depth": self.config.kraken_book_depth,
                "snapshot": True,
            },
        }

    @staticmethod
    def kafka_key_from_message(payload: dict[str, Any]) -> str:
        symbol = payload.get("symbol")

        if not symbol and isinstance(payload.get("result"), dict):
            symbol = payload["result"].get("symbol")

        if not symbol and isinstance(payload.get("data"), list) and payload["data"]:
            first = payload["data"][0]
            if isinstance(first, dict):
                symbol = first.get("symbol")

        return symbol or "unknown"

    def enrich_message(self, payload: dict[str, Any], received_at: datetime) -> dict[str, Any]:
        return {
            "source": "kraken",
            "ws_url": self.config.kraken_ws_url,
            "received_at": received_at.isoformat(),
            "channel": payload.get("channel") or self.config.kraken_channel,
            "payload": payload,
        }

    @staticmethod
    def is_market_data_message(payload: dict[str, Any]) -> bool:
        return isinstance(payload.get("data"), list) and bool(payload["data"])

    @staticmethod
    def _candidate_timestamps(payload: dict[str, Any]) -> list[Any]:
        candidates: list[Any] = []

        for key in ("time_in", "time_out", "timestamp", "time", "ts"):
            if key in payload:
                candidates.append(payload[key])

        data = payload.get("data")
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    for key in ("timestamp", "time", "ts"):
                        if key in item:
                            candidates.append(item[key])

        result = payload.get("result")
        if isinstance(result, dict):
            for key in ("timestamp", "time", "ts"):
                if key in result:
                    candidates.append(result[key])

        return candidates

    @staticmethod
    def extract_event_timestamp(payload: dict[str, Any]) -> datetime | None:
        for value in KrakenKafkaBridge._candidate_timestamps(payload):
            if isinstance(value, str):
                normalized = value.replace("Z", "+00:00")
                try:
                    parsed = datetime.fromisoformat(normalized)
                except ValueError:
                    continue
                if parsed.tzinfo is None:
                    return parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)

            if isinstance(value, (int, float)):
                epoch_value = value / 1000 if value > 1_000_000_000_000 else value
                return datetime.fromtimestamp(epoch_value, tz=timezone.utc)

        return None

    async def _subscribe(self, ws: WebSocketClientProtocol) -> None:
        message = self.build_subscribe_message()
        await ws.send(json.dumps(message))
        logger.info("Sent subscribe request: %s", message)

    async def _handle_connection(self, ws: WebSocketClientProtocol, stop_event: asyncio.Event) -> None:
        await self._subscribe(ws)

        while not stop_event.is_set():
            raw_message = await ws.recv()
            if isinstance(raw_message, bytes):
                raw_message = raw_message.decode("utf-8")

            try:
                payload = json.loads(raw_message)
            except json.JSONDecodeError:
                logger.warning("Skipping non-JSON message: %r", raw_message)
                continue

            received_at = datetime.now(timezone.utc)

            if payload.get("method") == "subscribe":
                if payload.get("success") is False:
                    logger.error("Kraken subscription failed: %s", payload)
                else:
                    logger.info("Kraken subscribe ack: %s", payload)

            key = self.kafka_key_from_message(payload)
            enriched = self.enrich_message(payload, received_at)
            publish_started = time.perf_counter()
            self.producer.publish(key=key, value=enriched)
            processing_latency_ms = (time.perf_counter() - publish_started) * 1000.0

            if self.influx_writer is not None and self.is_market_data_message(payload):
                event_timestamp = self.extract_event_timestamp(payload)
                source_event_latency_ms = None
                if event_timestamp is not None:
                    source_event_latency_ms = max(
                        0.0,
                        (received_at - event_timestamp).total_seconds() * 1000.0,
                    )

                self.influx_writer.write_market_data_latency(
                    symbol=key,
                    channel=enriched["channel"],
                    topic=self.config.kafka_topic,
                    message_type=payload.get("type", "update"),
                    bridge_processing_ms=processing_latency_ms,
                    source_event_latency_ms=source_event_latency_ms,
                    received_at=received_at,
                )

    async def run(self, stop_event: asyncio.Event) -> None:
        backoff_seconds = 1

        while not stop_event.is_set():
            try:
                logger.info(
                    "Connecting to Kraken ws=%s channel=%s symbols=%s",
                    self.config.kraken_ws_url,
                    self.config.kraken_channel,
                    self.config.kraken_symbols,
                )
                async with websockets.connect(
                    self.config.kraken_ws_url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=10,
                    max_size=None,
                ) as ws:
                    logger.info("Connected to Kraken WebSocket")
                    backoff_seconds = 1
                    await self._handle_connection(ws, stop_event)
            except asyncio.CancelledError:
                logger.info("Bridge cancelled")
                break
            except Exception as exc:
                logger.exception("Bridge error: %s", exc)
                if stop_event.is_set():
                    break
                logger.info("Reconnecting in %s second(s)", backoff_seconds)
                await asyncio.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, self._max_backoff_seconds)

        self.producer.flush()
