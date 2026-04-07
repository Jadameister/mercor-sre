# Kraken Kafka Bridge

A small Python project that connects to the Kraken Spot WebSocket, receives market data, publishes each message to Kafka, and writes per-message latency points into InfluxDB2.

## Features

- Kraken Spot WebSocket v2 client
- Supports `ticker` and `book` channels
- Publishes raw-plus-enriched messages to Kafka/Redpanda
- Writes market-data latency points to InfluxDB2
- Automatic reconnect with exponential backoff
- Environment-based configuration
- Docker Compose test stack with Grafana, Prometheus, Kafka, Loki, Elasticsearch, node monitoring, and container monitoring

## Project structure

```text
kraken_kafka_bridge/
├── .env.example
├── pyproject.toml
├── compose.yaml
├── Dockerfile
├── README.md
├── requirements.txt
├── docker/
│   ├── grafana/
│   └── prometheus/
└── src/
    └── kraken_kafka_bridge/
        ├── __init__.py
        ├── config.py
        ├── influx_writer.py
        ├── kafka_producer.py
        ├── kraken_ws.py
        ├── logging_setup.py
        └── main.py
```

## Prerequisites

- Python 3.12+
- Docker Desktop installed locally if you want to run the full Docker Compose stack
- A running Kafka or Redpanda broker
- A topic to publish into, for example `kraken-market-data`
- Optional InfluxDB2 instance if you want latency points outside Docker Compose

### Install Docker Desktop on your local machine

1. Download Docker Desktop from `https://www.docker.com/products/docker-desktop/`
2. Install Docker Desktop for your operating system
3. Launch Docker Desktop
4. Wait until Docker Desktop shows Docker is running
5. Verify the installation:

```bash
docker --version
docker compose version
```

If both commands succeed, your machine is ready to run the full stack locally.

## Setup

### 1. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

Using `requirements.txt`:

```bash
pip install -r requirements.txt
```

Or install as a package:

```bash
pip install -e .
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` as needed.

## Docker Compose test stack

The repository now includes a complete test stack on the dedicated Docker network `test-net`.

Services:

- `market-bridge`: Python injector consuming Kraken market data and publishing into Kafka
- `zookeeper`: Kafka coordination for the single-broker test stack
- `kafka`: single-broker Kafka for the test topic
- `influxdb`: InfluxDB2 storing latency points
- `prometheus`: metrics scraper
- `grafana`: dashboards with Prometheus, InfluxDB, Loki, and Elasticsearch datasources pre-provisioned
- `loki`: log storage for Grafana log queries
- `promtail`: ships structured bridge logs into Loki
- `elasticsearch`: searchable log storage for Grafana and API queries
- `filebeat`: ships structured bridge logs into Elasticsearch
- `node-exporter`: Linux node metrics
- `cadvisor`: Docker/container metrics
- `kafka-exporter`: Kafka broker and topic metrics
- `kafka-ui`: browser UI for Kafka topics, partitions, and messages

Start the environment:

```bash
docker compose up -d
```

Check container status:

```bash
docker compose ps
```

Watch the bridge logs:

```bash
docker compose logs -f market-bridge
```

Stop it:

```bash
docker compose down
```

Access points:

- Grafana: `http://localhost:3000` with `admin` / `admin12345`
- Prometheus: `http://localhost:9090`
- InfluxDB2: `http://localhost:8086`
- Loki: `http://localhost:3100`
- Elasticsearch: `http://localhost:9200`
- Kafka external listener: `localhost:19092`
- Kafka UI: `http://localhost:8088`
- cAdvisor: `http://localhost:8080`
- Kafka exporter metrics: `http://localhost:9308/metrics`

Login details:

- Grafana: username `admin`, password `admin12345`
- Prometheus: no login required
- cAdvisor: no login required
- InfluxDB2: username `admin`, password `admin12345`

Kafka access:

- External listener from your machine: `localhost:19092`
- Internal listener from Docker services: `kafka:9092`
- Kafka UI: `http://localhost:8088`

InfluxDB2 bootstrap values:

- Organization: `test-org`
- Bucket: `marketdata`
- Token: `marketdata-token`

The Grafana dashboard `Test Stack Overview` is provisioned automatically and includes:

- Linux node CPU and memory
- Docker CPU and memory by service
- Kafka topic partition and offset-growth views
- Influx-backed bridge latency views

The Grafana dashboard `Logs Observability` is also provisioned automatically and includes:

- A Loki logs panel for `market-bridge`
- An Elasticsearch logs panel for `market-bridge`
- A Loki log-volume panel grouped by log level

You do not need to install Grafana datasources or dashboards manually. They are provisioned automatically from the files under `docker/grafana/`.

## Step-by-step dashboard flow

1. Start the full stack:

```bash
docker compose up -d
```

2. Confirm the services are running:

```bash
docker compose ps
```

3. Open Grafana at `http://localhost:3000`
4. Log in with username `admin` and password `admin12345`
5. Open `Dashboards` -> `Test Stack` -> `Test Stack Overview`
6. Review these panels first:

- `Exporter Health` to confirm Prometheus targets are up
- `Docker CPU by Service` to confirm containers are active
- Kafka panels to confirm broker activity
- Influx latency panels to confirm the bridge is writing points

7. Open Prometheus at `http://localhost:9090`
8. Open `http://localhost:9090/targets` and verify scrape targets are `UP`
9. Open Kafka UI at `http://localhost:8088` to inspect topics, partitions, and messages
10. Open cAdvisor at `http://localhost:8080` for container-level resource details
11. Open InfluxDB at `http://localhost:8086` if you want to inspect bucket `marketdata` directly

Kafka UI does not require a separate login in this local Docker setup.

## Verifying live Kafka message flow

When the Python bridge starts successfully, you should see log lines for:

- WebSocket connection
- subscribe request
- subscribe acknowledgement

At the default `INFO` log level, the bridge does not print every market message that it publishes to Kafka. Quiet terminal output after the subscribe acknowledgement is therefore expected.

To verify that data is flowing into Kafka:

1. Open Kafka UI at `http://localhost:8088`
2. Open cluster `local`
3. Open `Topics`
4. Select topic `kraken-market-data`
5. Open `Messages`
6. Refresh or poll for new messages

If you are running the Python bridge locally on your machine, confirm that it is using the external Kafka listener:

```bash
echo $KAFKA_BOOTSTRAP_SERVERS
```

It should print:

```bash
localhost:19092
```

If you want more verbose terminal output, enable debug logging before starting the bridge:

```bash
export LOG_LEVEL=DEBUG
python run_local.py
```

With `DEBUG` logging enabled, Kafka delivery activity is logged to the terminal.

When the bridge runs in Docker Compose it also writes structured JSON logs to `./.logs/market-bridge.jsonl`. That file is the shared input used by Promtail and Filebeat to test log ingestion into Loki and Elasticsearch.

Note: on Docker Desktop, `node-exporter` and `cadvisor` report on the Linux VM backing Docker rather than native macOS host metrics.

## Running

The project supports two practical run modes:

- Full Docker mode: Kafka, InfluxDB, Grafana, Prometheus, and the Python bridge all run in Docker
- Hybrid mode: Kafka, InfluxDB, Grafana, and Prometheus run in Docker, but the Python bridge runs locally from your IDE or terminal

### Option 1: full Docker mode

Use this when you want the simplest end-to-end environment with one command.

1. Start the full stack:

```bash
docker compose up -d
```

2. Follow the bridge logs:

```bash
docker compose logs -f market-bridge
```

3. Open Grafana at `http://localhost:3000`
4. Open Prometheus at `http://localhost:9090`
5. Stop everything when finished:

```bash
docker compose down
```

In this mode, the Python bridge connects to Kafka using `kafka:9092` from inside Docker Compose.

### Option 2: hybrid mode with local Python app

Use this when you want to debug in PyCharm or run the bridge from your terminal, while still using Docker for Kafka, InfluxDB, and monitoring.

1. Start the infrastructure only:

```bash
docker compose up -d zookeeper kafka influxdb grafana prometheus node-exporter cadvisor kafka-exporter
```

2. Create and activate your virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Copy the environment template:

```bash
cp .env.example .env
```

5. For local Python execution against Docker Compose, make sure `.env` contains:

```env
KAFKA_BOOTSTRAP_SERVERS=localhost:19092
KAFKA_TOPIC=kraken-market-data
KRAKEN_CHANNEL=ticker
KRAKEN_SYMBOLS=BTC/USD,ETH/USD,XRP/USD
INFLUXDB_ENABLED=true
INFLUXDB_URL=http://localhost:8086
INFLUXDB_TOKEN=marketdata-token
INFLUXDB_ORG=test-org
INFLUXDB_BUCKET=marketdata
```

6. Run the bridge as a module from the repository root:

```bash
PYTHONPATH=src python -m kraken_kafka_bridge.main
```

Do not run `src/kraken_kafka_bridge/main.py` directly. It uses package-relative imports and must be run as a module.

### Option A: run as a module

This is the preferred local command:

```bash
PYTHONPATH=src python -m kraken_kafka_bridge.main
```

### Option B: run via installed script

```bash
kraken-kafka-bridge
```

## Example configurations

### Ticker stream

```env
KRAKEN_CHANNEL=ticker
KRAKEN_SYMBOLS=BTC/USD,ETH/USD,XRP/USD
```

### Order book stream

```env
KRAKEN_CHANNEL=book
KRAKEN_SYMBOLS=BTC/USD
KRAKEN_BOOK_DEPTH=10
```

## Kafka message shape

Each Kafka record value is JSON like:

```json
{
  "source": "kraken",
  "ws_url": "wss://ws.kraken.com/v2",
  "received_at": "2026-04-01T19:00:00.000000+00:00",
  "channel": "ticker",
  "payload": {
    "channel": "ticker",
    "type": "snapshot"
  }
}
```

The Kafka key is the best-effort `symbol` when available.

## InfluxDB latency measurement

When `INFLUXDB_ENABLED=true`, the bridge writes points into InfluxDB2 measurement `market_data_latency`.

Fields:

- `bridge_processing_ms`: time to enqueue a received market update into Kafka
- `source_event_latency_ms`: best-effort time from a timestamp embedded in the Kraken payload to local receipt, when such a timestamp is present

Tags:

- `source`
- `symbol`
- `channel`
- `topic`
- `message_type`

## Quick local Kafka/Redpanda test

If your broker is local:

```bash
export KAFKA_BOOTSTRAP_SERVERS=localhost:9092
export KAFKA_TOPIC=kraken-market-data
export INFLUXDB_ENABLED=false
PYTHONPATH=src python -m kraken_kafka_bridge.main
```

## Notes

- If your broker requires auth, uncomment the SASL-related variables in `.env`.
- If the Python process runs on your machine and Kafka runs in Docker Compose, use `KAFKA_BOOTSTRAP_SERVERS=localhost:19092`.
- If the Python process runs inside Docker Compose, use `KAFKA_BOOTSTRAP_SERVERS=kafka:9092`.
- The topic is not auto-created by this project. Create it on the broker side if auto-create is disabled.
