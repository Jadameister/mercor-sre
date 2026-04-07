from __future__ import annotations

import math
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _split_env(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [part.strip() for part in raw.split(",") if part.strip()]


def _seed(parts: tuple[object, ...]) -> int:
    text = "|".join(str(part) for part in parts)
    value = 0
    for char in text:
        value = (value * 131 + ord(char)) & 0x7FFFFFFF
    return value


def _slot_rng(ts: datetime, slot_seconds: int, *parts: object) -> random.Random:
    slot = int(ts.timestamp()) // slot_seconds
    return random.Random(_seed((slot_seconds, slot, *parts)))


@dataclass(slots=True)
class Config:
    influxdb_url: str
    influxdb_token: str
    influxdb_org: str
    influxdb_bucket: str
    backfill_days: int
    step_seconds: int
    run_forever: bool
    hosts: list[str]
    containers: list[str]
    interfaces: list[str]
    disks: list[str]

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            influxdb_url=os.getenv("INFLUXDB_URL", "http://host.docker.internal:8086"),
            influxdb_token=os.getenv("INFLUXDB_TOKEN", "marketdata-token"),
            influxdb_org=os.getenv("INFLUXDB_ORG", "test-org"),
            influxdb_bucket=os.getenv("INFLUXDB_BUCKET", "glances"),
            backfill_days=int(os.getenv("BACKFILL_DAYS", "7")),
            step_seconds=int(os.getenv("STEP_SECONDS", "60")),
            run_forever=_env_bool("RUN_FOREVER", "true"),
            hosts=_split_env("HOSTS", "edge-01,edge-02"),
            containers=_split_env("CONTAINERS", "nginx,redis,postgres,worker"),
            interfaces=_split_env("INTERFACES", "eth0,eth1"),
            disks=_split_env("DISKS", "sda,sdb"),
        )


def _hour_of_day(ts: datetime) -> float:
    return ts.hour + (ts.minute / 60.0)


def _daily_load(ts: datetime, host_index: int) -> float:
    hour = _hour_of_day(ts)
    morning = math.exp(-0.5 * ((hour - 9.5) / 2.0) ** 2)
    afternoon = math.exp(-0.5 * ((hour - 14.0) / 2.4) ** 2)
    base = 0.28 + morning * 0.55 + afternoon * 0.35
    weekday = ts.weekday()
    if weekday >= 5:
        base *= 0.55
    base *= 1.0 + 0.04 * math.sin(ts.timestamp() / 7200 + host_index)
    return max(0.08, min(1.4, base))


def _build_points(config: Config, ts: datetime) -> list[Point]:
    points: list[Point] = []
    interval = float(config.step_seconds)

    for host_index, host in enumerate(config.hosts):
        load = _daily_load(ts, host_index)
        host_rng = _slot_rng(ts, config.step_seconds, host)

        points.append(
            Point("load")
            .tag("hostname", host)
            .field("cpucore", 8 + host_index * 4)
            .field("min1", round(0.7 + load * 3.2 + host_rng.uniform(-0.12, 0.12), 3))
            .field("min5", round(0.6 + load * 2.8 + host_rng.uniform(-0.10, 0.10), 3))
            .field("min15", round(0.5 + load * 2.4 + host_rng.uniform(-0.08, 0.08), 3))
            .time(ts, WritePrecision.S)
        )

        cpu_user = max(3.0, min(88.0, 12.0 + load * 48.0 + host_rng.uniform(-4.0, 4.0)))
        cpu_system = max(2.0, min(28.0, 6.0 + load * 12.0 + host_rng.uniform(-1.5, 1.5)))
        cpu_iowait = max(0.2, min(12.0, 1.0 + load * 5.0 + host_rng.uniform(-0.7, 0.7)))
        points.append(
            Point("cpu")
            .tag("hostname", host)
            .field("user", round(cpu_user, 2))
            .field("system", round(cpu_system, 2))
            .field("iowait", round(cpu_iowait, 2))
            .time(ts, WritePrecision.S)
        )

        mem_total = float((32 + host_index * 16) * 1024**3)
        mem_ratio = max(0.25, min(0.96, 0.42 + load * 0.28 + host_rng.uniform(-0.04, 0.04)))
        mem_used = mem_total * mem_ratio
        points.append(
            Point("mem")
            .tag("hostname", host)
            .field("used", round(mem_used))
            .field("total", round(mem_total))
            .time(ts, WritePrecision.S)
        )

        swap_total = float(8 * 1024**3)
        swap_used = swap_total * max(0.02, min(0.55, 0.08 + load * 0.16 + host_rng.uniform(-0.02, 0.02)))
        points.append(
            Point("memswap")
            .tag("hostname", host)
            .field("used", round(swap_used))
            .field("total", round(swap_total))
            .time(ts, WritePrecision.S)
        )

        process_total = int(180 + load * 240 + host_rng.uniform(-8, 8))
        points.append(
            Point("processcount")
            .tag("hostname", host)
            .field("total", process_total)
            .time(ts, WritePrecision.S)
        )

        root_size = float((512 + host_index * 256) * 1024**3)
        days_into_cycle = (ts.timestamp() % (86400 * 30)) / 86400
        fs_ratio = max(0.22, min(0.92, 0.38 + days_into_cycle * 0.008 + host_rng.uniform(-0.01, 0.01)))
        fs_used = root_size * fs_ratio
        points.append(
            Point("fs")
            .tag("hostname", host)
            .tag("mnt_point", "/")
            .field("used", round(fs_used))
            .field("size", round(root_size))
            .field("percent", round(fs_ratio * 100.0, 2))
            .time(ts, WritePrecision.S)
        )

        ambient_temp = round(21.0 + 4.0 * load + host_rng.uniform(-0.8, 0.8), 2)
        cpu_temp = round(44.0 + 22.0 * load + host_rng.uniform(-2.0, 2.0), 2)
        points.append(
            Point("sensors")
            .tag("hostname", host)
            .tag("label", "Ambient")
            .field("value", ambient_temp)
            .time(ts, WritePrecision.S)
        )
        points.append(
            Point("sensors")
            .tag("hostname", host)
            .tag("label", "CPU")
            .field("value", cpu_temp)
            .time(ts, WritePrecision.S)
        )

        for interface_index, interface in enumerate(config.interfaces):
            iface_rng = _slot_rng(ts, config.step_seconds, host, interface)
            rx_rate = (18e6 + load * 70e6 + interface_index * 4e6) * (1.0 + iface_rng.uniform(-0.12, 0.12))
            tx_rate = (8e6 + load * 42e6 + interface_index * 3e6) * (1.0 + iface_rng.uniform(-0.12, 0.12))
            points.append(
                Point("network")
                .tag("hostname", host)
                .tag("interface_name", interface)
                .field("rx", round(rx_rate * interval / 8.0))
                .field("tx", round(tx_rate * interval / 8.0))
                .field("time_since_update", interval)
                .time(ts, WritePrecision.S)
            )

        for disk_index, disk in enumerate(config.disks):
            disk_rng = _slot_rng(ts, config.step_seconds, host, disk)
            read_rate = (5e6 + load * 16e6 + disk_index * 1.5e6) * (1.0 + disk_rng.uniform(-0.15, 0.15))
            write_rate = (3e6 + load * 11e6 + disk_index * 1.3e6) * (1.0 + disk_rng.uniform(-0.15, 0.15))
            points.append(
                Point("diskio")
                .tag("hostname", host)
                .tag("disk_name", disk)
                .field("read_bytes", round(read_rate * interval))
                .field("write_bytes", round(write_rate * interval))
                .field("time_since_update", interval)
                .time(ts, WritePrecision.S)
            )

        for container_index, container in enumerate(config.containers):
            container_rng = _slot_rng(ts, config.step_seconds, host, container)
            cpu_percent = max(0.2, min(96.0, 4.0 + load * (16.0 + container_index * 8.0) + container_rng.uniform(-3.0, 3.0)))
            mem_base = (256 + container_index * 384) * 1024**2
            mem_usage = mem_base * max(0.30, min(0.94, 0.48 + load * 0.22 + container_rng.uniform(-0.04, 0.04)))
            points.append(
                Point("docker")
                .tag("hostname", host)
                .tag("name", container)
                .field("memory_usage", round(mem_usage))
                .field("cpu_percent", round(cpu_percent, 2))
                .time(ts, WritePrecision.S)
            )

    return points


def _ensure_bucket(client: InfluxDBClient, config: Config) -> None:
    buckets_api = client.buckets_api()
    organizations_api = client.organizations_api()
    bucket = buckets_api.find_bucket_by_name(config.influxdb_bucket)
    if bucket is not None:
        return

    orgs = organizations_api.find_organizations(org=config.influxdb_org)
    if not orgs:
        raise RuntimeError(f"organization not found: {config.influxdb_org}")
    buckets_api.create_bucket(bucket_name=config.influxdb_bucket, org=orgs[0])


def backfill(write_api, config: Config) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    start = now - timedelta(days=config.backfill_days)
    current = start
    batch: list[Point] = []

    while current <= now:
        batch.extend(_build_points(config, current))
        if len(batch) >= 1000:
            write_api.write(bucket=config.influxdb_bucket, org=config.influxdb_org, record=batch)
            batch.clear()
        current += timedelta(seconds=config.step_seconds)

    if batch:
        write_api.write(bucket=config.influxdb_bucket, org=config.influxdb_org, record=batch)


def live_loop(write_api, config: Config) -> None:
    while True:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        points = _build_points(config, now)
        write_api.write(bucket=config.influxdb_bucket, org=config.influxdb_org, record=points)
        time.sleep(config.step_seconds)


def main() -> None:
    config = Config.from_env()
    print(
        f"[glances-generator] target={config.influxdb_url} bucket={config.influxdb_bucket} "
        f"days={config.backfill_days} step={config.step_seconds}s run_forever={config.run_forever}",
        flush=True,
    )

    with InfluxDBClient(
        url=config.influxdb_url,
        token=config.influxdb_token,
        org=config.influxdb_org,
        timeout=30_000,
    ) as client:
        _ensure_bucket(client, config)
        write_api = client.write_api(write_options=SYNCHRONOUS)
        backfill(write_api, config)
        print("[glances-generator] backfill complete", flush=True)
        if config.run_forever:
            live_loop(write_api, config)


if __name__ == "__main__":
    main()
