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
    cluster: str
    job: str
    listen_host: str
    listen_port: int
    backfill_days: int
    step_seconds: int
    prometheus_data_dir: str
    promtool_path: str
    marker_path: str
    nodes: list[str]

    @classmethod
    def from_env(cls) -> "Config":
        data_dir = os.getenv("PROMETHEUS_DATA_DIR", "/prometheus")
        return cls(
            cluster=os.getenv("ES_SYNTHETIC_CLUSTER", "synthetic-es-main"),
            job=os.getenv("ES_SYNTHETIC_JOB", "synthetic-elasticsearch-exporter"),
            listen_host=os.getenv("ES_EXPORTER_LISTEN_HOST", "0.0.0.0"),
            listen_port=int(os.getenv("ES_EXPORTER_LISTEN_PORT", "9314")),
            backfill_days=int(os.getenv("ES_BACKFILL_DAYS", "7")),
            step_seconds=int(os.getenv("ES_STEP_SECONDS", "300")),
            prometheus_data_dir=data_dir,
            promtool_path=os.getenv("PROMTOOL_PATH", "/usr/local/bin/promtool"),
            marker_path=os.getenv("ES_BACKFILL_MARKER", os.path.join(data_dir, ".synthetic-es-backfill-v1.done")),
            nodes=_split_env("ES_NODES", "es-hot-1,es-hot-2"),
        )


GAUGE_METRICS = {
    "elasticsearch_cluster_health_status",
    "elasticsearch_cluster_health_number_of_nodes",
    "elasticsearch_cluster_health_number_of_data_nodes",
    "elasticsearch_cluster_health_number_of_pending_tasks",
    "elasticsearch_cluster_health_active_primary_shards",
    "elasticsearch_cluster_health_active_shards",
    "elasticsearch_cluster_health_initializing_shards",
    "elasticsearch_cluster_health_relocating_shards",
    "elasticsearch_cluster_health_delayed_unassigned_shards",
    "elasticsearch_cluster_health_unassigned_shards",
    "elasticsearch_process_cpu_percent",
    "elasticsearch_process_open_files_count",
    "elasticsearch_jvm_memory_used_bytes",
    "elasticsearch_jvm_memory_max_bytes",
    "elasticsearch_jvm_memory_pool_peak_used_bytes",
    "elasticsearch_jvm_memory_committed_bytes",
    "elasticsearch_breakers_estimated_size_bytes",
    "elasticsearch_breakers_limit_size_bytes",
    "elasticsearch_os_load1",
    "elasticsearch_os_load5",
    "elasticsearch_os_load15",
    "elasticsearch_filesystem_data_available_bytes",
    "elasticsearch_filesystem_data_size_bytes",
    "elasticsearch_indices_docs",
    "elasticsearch_thread_pool_active_count",
    "elasticsearch_indices_fielddata_memory_size_bytes",
    "elasticsearch_indices_query_cache_memory_size_bytes",
    "elasticsearch_indices_segments_count",
    "elasticsearch_indices_segments_memory_bytes",
    "elasticsearch_indices_docs_primary",
    "elasticsearch_indices_store_size_bytes_primary",
    "elasticsearch_indices_store_size_bytes_total",
    "elasticsearch_indices_segment_doc_values_memory_bytes_primary",
    "elasticsearch_indices_segment_doc_values_memory_bytes_total",
    "elasticsearch_indices_segment_fields_memory_bytes_primary",
    "elasticsearch_indices_segment_fields_memory_bytes_total",
}


COUNTER_METRICS = {
    "elasticsearch_breakers_tripped",
    "elasticsearch_jvm_gc_collection_seconds_count",
    "elasticsearch_jvm_gc_collection_seconds_sum",
    "elasticsearch_indices_translog_operations",
    "elasticsearch_indices_translog_size_in_bytes",
    "elasticsearch_transport_tx_size_bytes_total",
    "elasticsearch_transport_rx_size_bytes_total",
    "elasticsearch_indices_indexing_index_total",
    "elasticsearch_indices_docs_deleted",
    "elasticsearch_indices_merges_docs_total",
    "elasticsearch_indices_merges_total",
    "elasticsearch_indices_merges_total_size_bytes_total",
    "elasticsearch_indices_search_query_time_seconds",
    "elasticsearch_indices_indexing_index_time_seconds_total",
    "elasticsearch_indices_merges_total_time_seconds_total",
    "elasticsearch_indices_store_throttle_time_seconds_total",
    "elasticsearch_indices_search_query_total",
    "elasticsearch_indices_search_fetch_total",
    "elasticsearch_indices_search_fetch_time_seconds",
    "elasticsearch_indices_refresh_total",
    "elasticsearch_indices_refresh_time_seconds_total",
    "elasticsearch_indices_flush_total",
    "elasticsearch_indices_flush_time_seconds",
    "elasticsearch_indices_get_exists_total",
    "elasticsearch_indices_get_exists_time_seconds",
    "elasticsearch_indices_get_missing_total",
    "elasticsearch_indices_get_missing_time_seconds",
    "elasticsearch_indices_get_total",
    "elasticsearch_indices_get_tota",
    "elasticsearch_indices_get_time_seconds",
    "elasticsearch_indices_indexing_delete_total",
    "elasticsearch_indices_indexing_delete_time_seconds_total",
    "elasticsearch_thread_pool_completed_count",
    "elasticsearch_thread_pool_rejected_count",
    "elasticsearch_indices_fielddata_evictions",
    "elasticsearch_indices_query_cache_evictions",
    "elasticsearch_indices_filter_cache_evictions",
}


ALL_METRICS = {name: "gauge" for name in GAUGE_METRICS}
ALL_METRICS.update({name: "counter" for name in COUNTER_METRICS})


def _metric_value(ts: datetime, config: Config, node_index: int, node_name: str) -> dict[str, float]:
    slot_rng = _slot_rng(ts, config.step_seconds, node_name)
    elapsed_hours = ts.timestamp() / 3600.0
    load_day = 0.5 + 0.35 * math.sin(elapsed_hours / 4.0 + node_index * 0.7)
    load_short = 0.08 * math.sin(elapsed_hours * 1.7 + node_index)
    load = max(0.18, min(0.96, load_day + load_short))

    cpu_percent = max(8.0, min(96.0, 22.0 + load * 58.0 + slot_rng.uniform(-3.0, 3.0)))
    load1 = max(0.1, 1.4 + load * 4.2 + slot_rng.uniform(-0.15, 0.15))
    load5 = max(0.1, 1.2 + load * 3.7 + slot_rng.uniform(-0.12, 0.12))
    load15 = max(0.1, 1.0 + load * 3.1 + slot_rng.uniform(-0.10, 0.10))

    jvm_max = float(8 * 1024**3)
    jvm_used = jvm_max * max(0.35, min(0.92, 0.48 + load * 0.22 + slot_rng.uniform(-0.02, 0.02)))
    jvm_committed = jvm_max * max(0.56, min(0.98, 0.72 + load * 0.10))
    jvm_peak = min(jvm_max, jvm_used * (1.05 + 0.04 * (node_index + 1)))

    fs_size = float((900 + node_index * 180) * 1024**3)
    fs_used_ratio = max(0.32, min(0.88, 0.52 + 0.12 * math.sin(elapsed_hours / 18.0 + node_index)))
    fs_available = fs_size * (1.0 - fs_used_ratio)

    docs = max(500_000.0, 4_200_000 + node_index * 420_000 + elapsed_hours * 1200 + 120_000 * math.sin(elapsed_hours / 6.0))
    docs_primary = docs * 0.58
    store_primary = docs_primary * 860
    store_total = docs * 1280

    gc_count = 10_000 + elapsed_hours * (0.8 + load * 1.2) * 360
    gc_sum = 2_200 + elapsed_hours * (0.2 + load * 0.35) * 360
    translog_ops = 80_000 + elapsed_hours * (20 + load * 65) * 360
    translog_size = 18_000_000 + elapsed_hours * (2_500 + load * 9_000) * 360
    breakers_tripped = elapsed_hours * (0.002 + max(0.0, load - 0.8) * 0.08)
    transport_tx = 9_000_000 + elapsed_hours * (150_000 + load * 750_000)
    transport_rx = 8_200_000 + elapsed_hours * (140_000 + load * 690_000)
    index_total = 240_000 + elapsed_hours * (90 + load * 300) * 360
    docs_deleted = 35_000 + elapsed_hours * (9 + load * 44) * 360
    merges_docs = 42_000 + elapsed_hours * (12 + load * 28) * 360
    merges_size = 260_000_000 + elapsed_hours * (80_000 + load * 320_000)
    search_query_time = 4_000 + elapsed_hours * (0.8 + load * 5.5) * 360
    indexing_time = 5_500 + elapsed_hours * (1.1 + load * 6.4) * 360
    merges_time = 2_400 + elapsed_hours * (0.5 + load * 2.1) * 360
    throttle_time = 180 + elapsed_hours * (0.03 + load * 0.18) * 360
    search_query_total = 800_000 + elapsed_hours * (110 + load * 520) * 360
    search_fetch_total = 600_000 + elapsed_hours * (70 + load * 310) * 360
    search_fetch_time = 2_900 + elapsed_hours * (0.6 + load * 3.8) * 360
    refresh_total = 180_000 + elapsed_hours * (35 + load * 120) * 360
    refresh_time = 1_000 + elapsed_hours * (0.4 + load * 1.1) * 360
    flush_total = 42_000 + elapsed_hours * (4 + load * 12) * 360
    flush_time = 190 + elapsed_hours * (0.02 + load * 0.09) * 360
    get_exists_total = 100_000 + elapsed_hours * (14 + load * 44) * 360
    get_exists_time = 640 + elapsed_hours * (0.09 + load * 0.28) * 360
    get_missing_total = 18_000 + elapsed_hours * (3 + load * 10) * 360
    get_missing_time = 150 + elapsed_hours * (0.02 + load * 0.05) * 360
    get_total = get_exists_total + get_missing_total
    get_time = get_exists_time + get_missing_time
    delete_total = 14_000 + elapsed_hours * (2 + load * 8) * 360
    delete_time = 90 + elapsed_hours * (0.01 + load * 0.04) * 360
    thread_completed = 300_000 + elapsed_hours * (120 + load * 600) * 360
    thread_rejected = elapsed_hours * (0.02 + max(0.0, load - 0.84) * 0.65) * 360
    fielddata_evictions = elapsed_hours * (0.003 + max(0.0, load - 0.8) * 0.08)
    query_cache_evictions = elapsed_hours * (0.03 + max(0.0, load - 0.72) * 0.45)
    filter_cache_evictions = elapsed_hours * (0.02 + max(0.0, load - 0.68) * 0.36)

    return {
        "elasticsearch_process_cpu_percent": cpu_percent,
        "elasticsearch_process_open_files_count": 2_000 + load * 6_000 + node_index * 350,
        "elasticsearch_jvm_memory_used_bytes": jvm_used,
        "elasticsearch_jvm_memory_max_bytes": jvm_max,
        "elasticsearch_jvm_memory_pool_peak_used_bytes": jvm_peak,
        "elasticsearch_jvm_memory_committed_bytes": jvm_committed,
        "elasticsearch_breakers_estimated_size_bytes": 180_000_000 + load * 900_000_000,
        "elasticsearch_breakers_limit_size_bytes": 1_400_000_000,
        "elasticsearch_breakers_tripped": breakers_tripped,
        "elasticsearch_os_load1": load1,
        "elasticsearch_os_load5": load5,
        "elasticsearch_os_load15": load15,
        "elasticsearch_jvm_gc_collection_seconds_count": gc_count,
        "elasticsearch_jvm_gc_collection_seconds_sum": gc_sum,
        "elasticsearch_indices_translog_operations": translog_ops,
        "elasticsearch_indices_translog_size_in_bytes": translog_size,
        "elasticsearch_filesystem_data_available_bytes": fs_available,
        "elasticsearch_filesystem_data_size_bytes": fs_size,
        "elasticsearch_transport_tx_size_bytes_total": transport_tx,
        "elasticsearch_transport_rx_size_bytes_total": transport_rx,
        "elasticsearch_indices_docs": docs,
        "elasticsearch_indices_indexing_index_total": index_total,
        "elasticsearch_indices_docs_deleted": docs_deleted,
        "elasticsearch_indices_merges_docs_total": merges_docs,
        "elasticsearch_indices_merges_total": 12_000 + elapsed_hours * (3 + load * 9) * 360,
        "elasticsearch_indices_merges_total_size_bytes_total": merges_size,
        "elasticsearch_indices_search_query_time_seconds": search_query_time,
        "elasticsearch_indices_indexing_index_time_seconds_total": indexing_time,
        "elasticsearch_indices_merges_total_time_seconds_total": merges_time,
        "elasticsearch_indices_store_throttle_time_seconds_total": throttle_time,
        "elasticsearch_indices_search_query_total": search_query_total,
        "elasticsearch_indices_search_fetch_total": search_fetch_total,
        "elasticsearch_indices_search_fetch_time_seconds": search_fetch_time,
        "elasticsearch_indices_refresh_total": refresh_total,
        "elasticsearch_indices_refresh_time_seconds_total": refresh_time,
        "elasticsearch_indices_flush_total": flush_total,
        "elasticsearch_indices_flush_time_seconds": flush_time,
        "elasticsearch_indices_get_exists_total": get_exists_total,
        "elasticsearch_indices_get_exists_time_seconds": get_exists_time,
        "elasticsearch_indices_get_missing_total": get_missing_total,
        "elasticsearch_indices_get_missing_time_seconds": get_missing_time,
        "elasticsearch_indices_get_total": get_total,
        "elasticsearch_indices_get_tota": get_total,
        "elasticsearch_indices_get_time_seconds": get_time,
        "elasticsearch_indices_indexing_delete_total": delete_total,
        "elasticsearch_indices_indexing_delete_time_seconds_total": delete_time,
        "elasticsearch_thread_pool_active_count": 2 + load * 9 + node_index,
        "elasticsearch_thread_pool_completed_count": thread_completed,
        "elasticsearch_thread_pool_rejected_count": thread_rejected,
        "elasticsearch_indices_fielddata_memory_size_bytes": 40_000_000 + load * 160_000_000,
        "elasticsearch_indices_fielddata_evictions": fielddata_evictions,
        "elasticsearch_indices_query_cache_memory_size_bytes": 80_000_000 + load * 200_000_000,
        "elasticsearch_indices_query_cache_evictions": query_cache_evictions,
        "elasticsearch_indices_filter_cache_evictions": filter_cache_evictions,
        "elasticsearch_indices_segments_count": 3_000 + load * 2_100 + node_index * 120,
        "elasticsearch_indices_segments_memory_bytes": 260_000_000 + load * 620_000_000,
        "elasticsearch_indices_docs_primary": docs_primary,
        "elasticsearch_indices_store_size_bytes_primary": store_primary,
        "elasticsearch_indices_store_size_bytes_total": store_total,
        "elasticsearch_indices_segment_doc_values_memory_bytes_primary": 24_000_000 + load * 44_000_000,
        "elasticsearch_indices_segment_doc_values_memory_bytes_total": 40_000_000 + load * 82_000_000,
        "elasticsearch_indices_segment_fields_memory_bytes_primary": 60_000_000 + load * 90_000_000,
        "elasticsearch_indices_segment_fields_memory_bytes_total": 96_000_000 + load * 160_000_000,
    }


def _cluster_metrics(ts: datetime, config: Config) -> list[tuple[str, dict[str, str], float]]:
    elapsed_hours = ts.timestamp() / 3600.0
    yellow = math.sin(elapsed_hours / 11.0) > 0.92
    red = math.sin(elapsed_hours / 37.0) > 0.992
    green = not yellow and not red
    rows: list[tuple[str, dict[str, str], float]] = []
    for node_name in config.nodes:
        base = {"cluster": config.cluster, "instance": node_name, "job": config.job}
        rows.extend(
            [
                ("elasticsearch_cluster_health_number_of_nodes", base, float(len(config.nodes))),
                ("elasticsearch_cluster_health_number_of_data_nodes", base, float(len(config.nodes))),
                ("elasticsearch_cluster_health_number_of_pending_tasks", base, float(1 + max(0, int(8 * max(0.0, math.sin(elapsed_hours / 3.0)))))),
                ("elasticsearch_cluster_health_active_primary_shards", base, 192.0),
                ("elasticsearch_cluster_health_active_shards", base, 384.0 if green else 372.0),
                ("elasticsearch_cluster_health_initializing_shards", base, 0.0 if green else 4.0),
                ("elasticsearch_cluster_health_relocating_shards", base, 0.0 if green else 2.0),
                ("elasticsearch_cluster_health_delayed_unassigned_shards", base, 0.0 if green else 1.0),
                ("elasticsearch_cluster_health_unassigned_shards", base, 0.0 if green else (3.0 if yellow else 12.0)),
                ("elasticsearch_cluster_health_status", {**base, "color": "green"}, 1.0 if green else 0.0),
                ("elasticsearch_cluster_health_status", {**base, "color": "yellow"}, 1.0 if yellow else 0.0),
                ("elasticsearch_cluster_health_status", {**base, "color": "red"}, 1.0 if red else 0.0),
            ]
        )
    return rows


def _instant_samples(ts: datetime, config: Config) -> list[tuple[str, dict[str, str], float]]:
    samples = _cluster_metrics(ts, config)
    for node_index, node_name in enumerate(config.nodes):
        labels = {"cluster": config.cluster, "name": node_name, "instance": node_name, "job": config.job}
        for metric, value in _metric_value(ts, config, node_index, node_name).items():
            samples.append((metric, labels, value))
    return samples


def _format_labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    parts = [f'{key}="{value}"' for key, value in sorted(labels.items())]
    return "{" + ",".join(parts) + "}"


def _render_openmetrics(ts: datetime, config: Config) -> str:
    seen_types: set[str] = set()
    lines: list[str] = []
    for metric, labels, value in _instant_samples(ts, config):
        if metric not in seen_types:
            seen_types.add(metric)
            lines.append(f"# TYPE {metric} {ALL_METRICS.get(metric, 'gauge')}")
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
            # promtool's OpenMetrics importer expects unix timestamps in seconds here.
            # Writing milliseconds pushes samples ~1000x into the future.
            timestamp_s = int(current.timestamp())
            for metric, labels, value in _instant_samples(current, config):
                if metric not in wrote_types:
                    wrote_types.add(metric)
                    handle.write(f"# TYPE {metric} {ALL_METRICS.get(metric, 'gauge')}\n")
                handle.write(f"{metric}{_format_labels(labels)} {value:.6f} {timestamp_s}\n")
            current += timedelta(seconds=config.step_seconds)
        handle.write("# EOF\n")


def run_backfill(config: Config, force: bool = False) -> None:
    if os.path.exists(config.marker_path) and not force:
        print(f"[synthetic-es] backfill already present: {config.marker_path}", flush=True)
        return

    os.makedirs(config.prometheus_data_dir, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".openmetrics", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        print(
            f"[synthetic-es] generating {config.backfill_days}d of Prometheus history "
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
        print("[synthetic-es] backfill complete", flush=True)
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
    print(f"[synthetic-es] exporter listening on {config.listen_host}:{config.listen_port}", flush=True)
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
