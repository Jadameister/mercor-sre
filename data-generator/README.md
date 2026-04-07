# Data Generator

This directory contains the synthetic data generators used by the dashboards in the project.

Files:

- `app.py`: writes Glances-style system data into InfluxDB
- `elasticsearch_exporter_generator.py`: serves synthetic Prometheus `elasticsearch_*` metrics and can backfill 7 days into Prometheus TSDB
- `kafka_exporter_generator.py`: serves synthetic Prometheus `kafka_*` metrics and can backfill 7 days into Prometheus TSDB

The standalone Docker image in this folder is for the Glances-style InfluxDB generator only.

## Prerequisites

The Glances generator needs a reachable InfluxDB instance.

Default values expected by this repo:

- URL: `http://host.docker.internal:8086`
- org: `test-org`
- token: `marketdata-token`
- bucket: `glances`

If you are using the project Docker Compose stack, start that first:

```bash
docker compose up -d influxdb grafana
```

If you are using the all-in-one image, the generator already runs inside that container and you do not need to start `data-generator` separately.

## Build

```bash
docker build -f data-generator/Dockerfile -t mercor-data-generator .
```

## Run once for backfill only

```bash
docker run --rm \
  -e INFLUXDB_URL=http://host.docker.internal:8086 \
  -e INFLUXDB_BUCKET=glances \
  -e BACKFILL_DAYS=7 \
  -e RUN_FOREVER=false \
  mercor-data-generator
```

## Run continuously in the background

```bash
docker run -d --name mercor-data-generator \
  -e INFLUXDB_URL=http://host.docker.internal:8086 \
  -e INFLUXDB_BUCKET=glances \
  -e BACKFILL_DAYS=7 \
  -e RUN_FOREVER=true \
  mercor-data-generator
```

## Run locally without Docker

From the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r data-generator/requirements.txt
export INFLUXDB_URL=http://localhost:8086
export INFLUXDB_TOKEN=marketdata-token
export INFLUXDB_ORG=test-org
export INFLUXDB_BUCKET=glances
export BACKFILL_DAYS=7
export STEP_SECONDS=60
export RUN_FOREVER=true
python data-generator/app.py
```

Use `RUN_FOREVER=false` if you only want the historical backfill.

## How the Glances generator works

`app.py` builds synthetic host telemetry for:

- load
- process counts
- CPU
- memory and swap
- network interfaces
- disk I/O
- filesystem usage
- temperature sensors
- container CPU and memory

Generation behavior:

- writes 7 days of historical data first
- then keeps writing new points every `STEP_SECONDS`
- uses deterministic time-slot randomness so the charts look stable and realistic instead of completely random on each refresh

The first startup can take a little time because the 7-day backfill is written before the live loop begins.

Important environment variables:

- `INFLUXDB_URL`
- `INFLUXDB_TOKEN`
- `INFLUXDB_ORG`
- `INFLUXDB_BUCKET`
- `BACKFILL_DAYS`
- `STEP_SECONDS`
- `RUN_FOREVER`
- `HOSTS`
- `CONTAINERS`
- `INTERFACES`
- `DISKS`

The generated schema matches the Glances dashboard expectations:
- bucket: `glances`
- measurements: `load`, `processcount`, `cpu`, `mem`, `network`, `memswap`, `diskio`, `fs`, `sensors`, `docker`
- tags: `hostname`, `interface_name`, `disk_name`, `name`, `label`, `mnt_point`

Default synthetic values:

- hosts: `edge-01`, `edge-02`
- interfaces: `eth0`, `eth1`
- disks: `sda`, `sdb`
- containers: `nginx`, `redis`, `postgres`, `worker`

## How to verify data was created

### 1. Check the generator logs

Docker:

```bash
docker logs -f mercor-data-generator
```

You should see messages like:

- target URL and bucket
- `backfill complete`

### 2. Check InfluxDB bucket contents

If InfluxDB is running in Docker Compose:

```bash
docker exec influxdb influx query '
from(bucket: "glances")
  |> range(start: -15m)
  |> limit(n: 10)
'
```

If you are using the all-in-one container:

```bash
docker exec mercor-sre influx query '
from(bucket: "glances")
  |> range(start: -15m)
  |> limit(n: 10)
'
```

If the bucket has data, you should see rows from measurements like `network`, `diskio`, `cpu`, or `docker`.

### 3. Check Grafana

Open the Glances dashboard and make sure:

- datasource = `glances`
- `interface = eth0`
- `disk = sda`

If the dashboard still looks empty:

- set the time range to `Last 7 days` or `Last 1 hour`
- refresh the dashboard
- reselect `host`, `interface`, and `disk`

## Common reason for seeing no data

- InfluxDB is not running
- the generator cannot reach `INFLUXDB_URL`
- the generator is still in the backfill step
- the dashboard variables are not selected
- you are running the standalone generator while looking at the all-in-one stack, or the reverse

## Elasticsearch and Kafka synthetic generators

These two generators are used by the all-in-one stack and are not started by `data-generator/Dockerfile` directly.

### Elasticsearch

Run manually from the repo root if needed:

```bash
python3 data-generator/elasticsearch_exporter_generator.py --serve-only
```

Backfill only:

```bash
python3 data-generator/elasticsearch_exporter_generator.py --backfill-only
```

### Kafka

Run manually from the repo root if needed:

```bash
python3 data-generator/kafka_exporter_generator.py --serve-only
```

Backfill only:

```bash
python3 data-generator/kafka_exporter_generator.py --backfill-only
```

In the all-in-one image both of these are wired automatically:

- Prometheus backfill runs before Prometheus starts
- live exporters continue serving metrics after startup
