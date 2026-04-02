from __future__ import annotations

import asyncio
import logging
import signal
import sys

from .config import AppConfig
from .influx_writer import InfluxLatencyWriter
from .kafka_producer import KafkaMarketDataProducer
from .kraken_ws import KrakenKafkaBridge
from .logging_setup import configure_logging

logger = logging.getLogger(__name__)


async def async_main() -> None:
    config = AppConfig.from_env()
    configure_logging(config.log_level)

    producer = KafkaMarketDataProducer(config.kafka_config(), config.kafka_topic)
    influx_writer = InfluxLatencyWriter.from_config(config)
    bridge = KrakenKafkaBridge(config, producer, influx_writer)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_stop() -> None:
        logger.info("Stop requested")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_args: request_stop())

    try:
        await bridge.run(stop_event)
    finally:
        if influx_writer is not None:
            influx_writer.close()


def main() -> None:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
