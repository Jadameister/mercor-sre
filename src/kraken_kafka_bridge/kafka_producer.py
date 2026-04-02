from __future__ import annotations

import json
import logging
from typing import Any

from confluent_kafka import Producer

logger = logging.getLogger(__name__)


class KafkaMarketDataProducer:
    def __init__(self, config: dict[str, Any], topic: str) -> None:
        self._producer = Producer(config)
        self._topic = topic

    @staticmethod
    def _delivery_report(err, msg) -> None:
        if err is not None:
            logger.error("Kafka delivery failed: %s", err)
            return

        logger.debug(
            "Kafka delivered topic=%s partition=%s offset=%s key=%s",
            msg.topic(),
            msg.partition(),
            msg.offset(),
            msg.key().decode("utf-8") if msg.key() else None,
        )

    def publish(self, *, key: str, value: dict[str, Any]) -> None:
        encoded_value = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self._producer.produce(
            topic=self._topic,
            key=key.encode("utf-8"),
            value=encoded_value,
            on_delivery=self._delivery_report,
        )
        self._producer.poll(0)

    def flush(self, timeout: float = 10.0) -> None:
        self._producer.flush(timeout)
