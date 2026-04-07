from __future__ import annotations

import argparse
import math
import os
import random
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _seed(parts: tuple[object, ...]) -> int:
    text = "|".join(str(part) for part in parts)
    value = 0
    for char in text:
        value = (value * 131 + ord(char)) & 0x7FFFFFFF
    return value


def _slot_rng(ts: datetime, slot_seconds: int, *parts: object) -> random.Random:
    slot = int(ts.timestamp()) // slot_seconds
    return random.Random(_seed((slot_seconds, slot, *parts)))


def _split_env(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [part.strip() for part in raw.split(",") if part.strip()]


@dataclass(slots=True)
class Config:
    namespace: str
    listen_host: str
    listen_port: int
    backfill_days: int
    step_seconds: int
    prometheus_data_dir: str
    promtool_path: str
    marker_path: str
    brokers: list[str]
    topics: list[str]
    consumer_groups: list[str]
    partitions_per_topic: int
    replication_factor: int

    @classmethod
    def from_env(cls) -> "Config":
        data_dir = os.getenv("PROMETHEUS_DATA_DIR", "/prometheus")
        return cls(
            namespace=os.getenv("KAFKA_SYNTHETIC_NAMESPACE", "kafka"),
            listen_host=os.getenv("KAFKA_EXPORTER_LISTEN_HOST", "0.0.0.0"),
            listen_port=int(os.getenv("KAFKA_EXPORTER_LISTEN_PORT", "9308")),
            backfill_days=int(os.getenv("KAFKA_BACKFILL_DAYS", "7")),
            step_seconds=int(os.getenv("KAFKA_STEP_SECONDS", "60")),
            prometheus_data_dir=data_dir,
            promtool_path=os.getenv("PROMTOOL_PATH", "/usr/local/bin/promtool"),
            marker_path=os.getenv("KAFKA_BACKFILL_MARKER", os.path.join(data_dir, ".synthetic-kafka-backfill-v1.done")),
            brokers=_split_env("KAFKA_BROKERS", "broker-1,broker-2,broker-3"),
            topics=_split_env("KAFKA_TOPICS", "kraken-market-data,orders,payments"),
            consumer_groups=_split_env("KAFKA_CONSUMER_GROUPS", "analytics,etl,alerts"),
            partitions_per_topic=int(os.getenv("KAFKA_PARTITIONS_PER_TOPIC", "6")),
            replication_factor=int(os.getenv("KAFKA_REPLICATION_FACTOR", "3")),
        )


GAUGE_METRICS = {
    "kafka_brokers",
    "kafka_topic_partitions",
    "kafka_topic_partition_leader",
    "kafka_topic_partition_leader_is_preferred",
    "kafka_topic_partition_replicas",
    "kafka_topic_partition_in_sync_replica",
    "kafka_topic_partition_under_replicated_partition",
    "kafka_topic_partition_current_offset",
    "kafka_consumergroup_current_offset",
    "kafka_consumergroup_lag",
    "kafka_log_log_size",
}


def _topic_load(ts: datetime, step_seconds: int, topic_index: int, partition_index: int) -> float:
    rng = _slot_rng(ts, step_seconds, "topic", topic_index, partition_index)
    elapsed_hours = ts.timestamp() / 3600.0
    daily = 0.58 + 0.28 * math.sin(elapsed_hours / 5.0 + topic_index * 0.9 + partition_index * 0.17)
    short = 0.10 * math.sin(elapsed_hours * 1.8 + topic_index * 0.7 + partition_index * 0.31)
    noise = rng.uniform(-0.04, 0.04)
    return max(0.15, min(0.98, daily + short + noise))


def _current_offset(ts: datetime, step_seconds: int, topic_index: int, partition_index: int) -> float:
    elapsed_hours = ts.timestamp() / 3600.0
    load = _topic_load(ts, step_seconds, topic_index, partition_index)
    base = 120_000 + topic_index * 280_000 + partition_index * 36_000
    rate_per_sec = 35 + topic_index * 18 + partition_index * 3 + load * 220
    return base + elapsed_hours * 3600 * rate_per_sec


def _consumer_offset(
    topic_offset: float,
    ts: datetime,
    step_seconds: int,
    topic_index: int,
    partition_index: int,
    group_index: int,
) -> tuple[float, float]:
    rng = _slot_rng(ts, step_seconds, "group", topic_index, partition_index, group_index)
    elapsed_hours = ts.timestamp() / 3600.0
    lag_floor = 60 + topic_index * 20 + partition_index * 9 + group_index * 35
    lag_wave = 420 * (1.0 + math.sin(elapsed_hours / 3.4 + group_index * 0.8 + partition_index * 0.2))
    lag_noise = rng.uniform(0.0, 110.0)
    lag = max(0.0, lag_floor + lag_wave + lag_noise)
    current = max(0.0, topic_offset - lag)
    return current, lag


def _partition_rows(ts: datetime, config: Config) -> list[tuple[str, dict[str, str], float]]:
    rows: list[tuple[str, dict[str, str], float]] = []
    broker_count = max(1, len(config.brokers))
    for broker_id, broker_name in enumerate(config.brokers, start=1):
        rows.append(
            (
                "kafka_brokers",
                {"namespace": config.namespace, "id": str(broker_id), "address": broker_name},
                float(broker_id),
            )
        )

    for topic_index, topic in enumerate(config.topics):
        rows.append(("kafka_topic_partitions", {"namespace": config.namespace, "topic": topic}, float(config.partitions_per_topic)))
        for partition_index in range(config.partitions_per_topic):
            partition = str(partition_index)
            offset = _current_offset(ts, config.step_seconds, topic_index, partition_index)
            leader = 1 + ((topic_index + partition_index) % broker_count)
            leader_preferred = 0.0 if (topic_index + partition_index) % 11 == 0 else 1.0
            under_replicated = 1.0 if (topic_index + partition_index) % 17 == 0 else 0.0
            in_sync = float(max(1, config.replication_factor - int(under_replicated)))
            log_size = offset * (720 + topic_index * 80 + partition_index * 7)
            base_labels = {"namespace": config.namespace, "topic": topic, "partition": partition}
            rows.extend(
                [
                    ("kafka_topic_partition_leader", base_labels, float(leader)),
                    ("kafka_topic_partition_leader_is_preferred", base_labels, leader_preferred),
                    ("kafka_topic_partition_replicas", base_labels, float(config.replication_factor)),
                    ("kafka_topic_partition_in_sync_replica", base_labels, in_sync),
                    ("kafka_topic_partition_under_replicated_partition", base_labels, under_replicated),
                    ("kafka_topic_partition_current_offset", base_labels, offset),
                    ("kafka_log_log_size", base_labels, log_size),
                ]
            )
            for group_index, consumergroup in enumerate(config.consumer_groups):
                current_offset, lag = _consumer_offset(offset, ts, config.step_seconds, topic_index, partition_index, group_index)
                rows.extend(
                    [
                        (
                            "kafka_consumergroup_current_offset",
                            {**base_labels, "consumergroup": consumergroup},
                            current_offset,
                        ),
                        (
                            "kafka_consumergroup_lag",
                            {**base_labels, "consumergroup": consumergroup},
                            lag,
                        ),
                    ]
                )
    return rows


def _format_labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    parts = [f'{key}="{value}"' for key, value in sorted(labels.items())]
    return "{" + ",".join(parts) + "}"


def _render_openmetrics(ts: datetime, config: Config) -> str:
    lines: list[str] = []
    wrote_types: set[str] = set()
    for metric, labels, value in _partition_rows(ts, config):
        if metric not in wrote_types:
            wrote_types.add(metric)
            lines.append(f"# TYPE {metric} gauge")
        lines.append(f"{metric}{_format_labels(labels)} {value:.6f}")
    lines.append("# EOF")
    return "\n".join(lines) + "\n"


def _write_backfill_openmetrics(path: str, config: Config) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    start = now - timedelta(days=config.backfill_days)
    current = start
    wrote_types: set[str] = set()
    with open(path, "w", encoding="utf-8") as handle:
        while current <= now:
            timestamp_s = int(current.timestamp())
            for metric, labels, value in _partition_rows(current, config):
                if metric not in wrote_types:
                    wrote_types.add(metric)
                    handle.write(f"# TYPE {metric} gauge\n")
                handle.write(f"{metric}{_format_labels(labels)} {value:.6f} {timestamp_s}\n")
            current += timedelta(seconds=config.step_seconds)
        handle.write("# EOF\n")


def run_backfill(config: Config, force: bool = False) -> None:
    if os.path.exists(config.marker_path) and not force:
        print(f"[synthetic-kafka] backfill already present: {config.marker_path}", flush=True)
        return

    os.makedirs(config.prometheus_data_dir, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".openmetrics", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        print(
            f"[synthetic-kafka] generating {config.backfill_days}d of Prometheus history "
            f"at {config.step_seconds}s resolution",
            flush=True,
        )
        _write_backfill_openmetrics(tmp_path, config)
        subprocess.run(
            [config.promtool_path, "tsdb", "create-blocks-from", "openmetrics", tmp_path, config.prometheus_data_dir],
            check=True,
        )
        with open(config.marker_path, "w", encoding="utf-8") as marker:
            marker.write(datetime.now(timezone.utc).isoformat())
        print("[synthetic-kafka] backfill complete", flush=True)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


class MetricsHandler(BaseHTTPRequestHandler):
    config: Config

    def do_GET(self) -> None:  # noqa: N802
        if self.path not in {"/metrics", "/metrics/"}:
            self.send_response(404)
            self.end_headers()
            return

        body = _render_openmetrics(datetime.now(timezone.utc).replace(microsecond=0), self.config).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/openmetrics-text; version=1.0.0; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def serve(config: Config) -> None:
    class Handler(MetricsHandler):
        pass

    Handler.config = config
    server = ThreadingHTTPServer((config.listen_host, config.listen_port), Handler)
    print(f"[synthetic-kafka] exporter listening on {config.listen_host}:{config.listen_port}", flush=True)
    server.serve_forever()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill-only", action="store_true")
    parser.add_argument("--serve-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = Config.from_env()
    if not args.serve_only:
        run_backfill(config, force=args.force)
    if not args.backfill_only:
        serve(config)


if __name__ == "__main__":
    main()
