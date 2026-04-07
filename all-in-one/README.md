# mercor-sre — All-in-One Docker Image

Single container running the full stack, managed by supervisord.

---

## Build

```bash
docker build -f all-in-one/Dockerfile -t mercor-sre-all-in-one .
```

---

## Run

```bash
docker run -d --name mercor-sre \
  -p 3000:3000 -p 9090:9090 -p 8086:8086 -p 3100:3100 -p 9200:9200 -p 19092:19092 -p 8088:8088 -p 9308:9308 \
  mercor-sre-all-in-one
```

> **Mac (Docker Desktop) note:** `--sysctl vm.max_map_count=262144` is not allowed on `docker run`.
> Before running the container, set the Elasticsearch kernel flag in the Docker Desktop VM:
> ```bash
> docker run --rm --privileged alpine sysctl -w vm.max_map_count=262144
> ```
> Re-run this if you restart Docker Desktop.

---

## Check services are up

```bash
docker exec mercor-sre supervisorctl status
```

All programs should show `RUNNING`. `influxdb-init` will show `EXITED` — that is expected (it runs once at startup to create the org/bucket/token).

---

## UI access

### Grafana — http://localhost:3000
- Username: `admin`
- Password: `admin12345`
- Dashboards are pre-provisioned under **Dashboards → Test Stack**:
  - **Test Stack Overview** — CPU, memory, Kafka offsets, InfluxDB latency
  - **Logs Observability** — Loki and Elasticsearch log panels
  - **Docker Latency Drilldown** — per-container latency breakdown
- Datasources are pre-provisioned (no manual setup needed):
  - Prometheus
  - InfluxDB
  - Loki
  - Elasticsearch

### Prometheus — http://localhost:9090
- No login required
- Check scrape targets: http://localhost:9090/targets
- All targets should show `UP` once the stack is fully started (~60s)

### InfluxDB — http://localhost:8086
- Username: `admin`
- Password: `admin12345`
- Organization: `test-org`
- Bucket: `marketdata`
- Token: `marketdata-token`
- Market data latency points are written to measurement `market_data_latency`

### Loki — http://localhost:3100
- No UI (query via Grafana → Explore → Loki datasource)
- Receives structured logs from the `market-bridge` app via Promtail

### Elasticsearch — http://localhost:9200
- No login required (security disabled)
- Index pattern: `market-bridge-logs-*`
- Query via Grafana → Explore → Elasticsearch datasource
- Or directly: `curl http://localhost:9200/_cat/indices?v`

### Kafka — localhost:19092
- No UI (use kafka-ui below for browser access)
- Connect external producers/consumers to `localhost:19092`

### kafka-ui — http://localhost:8088
- No login required
- Cluster name: `local`
- Inspect topics, partitions, consumer groups, and live messages
- Topic to watch: `kraken-market-data`

### kafka-exporter metrics — http://localhost:9308/metrics
- Raw Prometheus metrics for Kafka broker and topics
- Scraped automatically by Prometheus

---

## Useful commands

```bash
# Stream all logs
docker logs -f mercor-sre

# Check service status
docker exec mercor-sre supervisorctl status

# Restart a service
docker exec mercor-sre supervisorctl restart market-bridge

# Tail a specific service log
docker exec mercor-sre supervisorctl tail -f kafka
docker exec mercor-sre supervisorctl tail -f elasticsearch
docker exec mercor-sre supervisorctl tail -f grafana

# Stop the container
docker stop mercor-sre

# Remove it
docker rm mercor-sre
```

---

## Services inside the container

| Service | Port | Notes |
|---|---|---|
| Grafana | 3000 | Dashboards + datasources pre-provisioned |
| Prometheus | 9090 | Scrapes all localhost targets |
| InfluxDB 2.7 | 8086 | Auto-initialized on first start |
| Loki | 3100 | Log storage for Grafana |
| Promtail | — | Ships market-bridge logs to Loki |
| Elasticsearch | 9200 | Security disabled, single-node |
| Filebeat | — | Ships market-bridge logs to Elasticsearch |
| ZooKeeper | 2181 | Internal only |
| Kafka | 19092 | External listener on 19092 |
| kafka-ui | 8088 | Browser UI for Kafka |
| kafka-exporter | 9308 | Kafka metrics for Prometheus |
| node-exporter | 9100 | Internal only |
| cadvisor | 8080 | Internal only |
| market-bridge | — | Kraken WebSocket → Kafka + InfluxDB |
