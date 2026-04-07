# all-in-one/Dockerfile
# Single self-contained image bundling the full observability stack:
#   Grafana OSS, Prometheus, InfluxDB 2.7, Loki, Promtail,
#   Elasticsearch 8.x, Filebeat, Apache Kafka + ZooKeeper,
#   kafka-exporter, kafka-ui, node-exporter, cadvisor,
#   and the Python kraken-kafka-bridge app.
#   All processes are managed by supervisord.
#
# Build context: repo root
#   docker build -f all-in-one/Dockerfile -t mercor-sre-all-in-one .
#
# Run (Elasticsearch requires vm.max_map_count; cadvisor needs --privileged):
#   docker run -d --name mercor-sre \
#     --sysctl vm.max_map_count=262144 \
#     -p 3000:3000   `# Grafana` \
#     -p 9090:9090   `# Prometheus` \
#     -p 8086:8086   `# InfluxDB` \
#     -p 3100:3100   `# Loki` \
#     -p 9200:9200   `# Elasticsearch` \
#     -p 19092:19092 `# Kafka (external)` \
#     -p 8088:8088   `# kafka-ui` \
#     -p 9308:9308   `# kafka-exporter` \
#     mercor-sre-all-in-one

FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive
ARG TARGETARCH

# ── version pins (override with --build-arg) ─────────────────────────────────
ARG GRAFANA_VERSION=11.1.4
ARG PROMETHEUS_VERSION=2.54.1
ARG LOKI_VERSION=3.1.1
ARG INFLUXDB_VERSION=2.7.10
ARG ELASTICSEARCH_VERSION=8.15.3
ARG KAFKA_VERSION=3.6.2
ARG SCALA_VERSION=2.13
ARG KAFKA_EXPORTER_VERSION=1.8.0
ARG KAFKA_UI_VERSION=0.7.2
ARG NODE_EXPORTER_VERSION=1.8.2
ARG CADVISOR_VERSION=0.49.1
ARG PYTHONUNBUFFERED=1

# ── 1. base system packages ──────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl wget gnupg2 \
    supervisor \
    python3 python3-pip \
    openjdk-17-jre-headless \
    adduser libfontconfig1 musl \
    netcat-openbsd \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# ── 2. Grafana OSS ───────────────────────────────────────────────────────────
RUN wget -q "https://dl.grafana.com/oss/release/grafana_${GRAFANA_VERSION}_${TARGETARCH}.deb" \
         -O /tmp/grafana.deb \
 && dpkg -i /tmp/grafana.deb \
 && rm /tmp/grafana.deb

# ── 3. Prometheus ────────────────────────────────────────────────────────────
RUN wget -q "https://github.com/prometheus/prometheus/releases/download/v${PROMETHEUS_VERSION}/prometheus-${PROMETHEUS_VERSION}.linux-${TARGETARCH}.tar.gz" \
         -O /tmp/prometheus.tar.gz \
 && tar -xzf /tmp/prometheus.tar.gz -C /tmp \
 && install -m 755 /tmp/prometheus-${PROMETHEUS_VERSION}.linux-${TARGETARCH}/prometheus /usr/local/bin/prometheus \
 && install -m 755 /tmp/prometheus-${PROMETHEUS_VERSION}.linux-${TARGETARCH}/promtool /usr/local/bin/promtool \
 && mkdir -p /usr/share/prometheus \
 && cp -r /tmp/prometheus-${PROMETHEUS_VERSION}.linux-${TARGETARCH}/console_libraries /usr/share/prometheus/ \
 && cp -r /tmp/prometheus-${PROMETHEUS_VERSION}.linux-${TARGETARCH}/consoles /usr/share/prometheus/ \
 && rm -rf /tmp/prometheus.tar.gz /tmp/prometheus-${PROMETHEUS_VERSION}.linux-${TARGETARCH}

# ── 4. Loki ──────────────────────────────────────────────────────────────────
RUN wget -q "https://github.com/grafana/loki/releases/download/v${LOKI_VERSION}/loki-linux-${TARGETARCH}.zip" \
         -O /tmp/loki.zip \
 && unzip -q /tmp/loki.zip "loki-linux-${TARGETARCH}" -d /tmp \
 && install -m 755 /tmp/loki-linux-${TARGETARCH} /usr/local/bin/loki \
 && rm -rf /tmp/loki.zip /tmp/loki-linux-${TARGETARCH}

# ── 5. Promtail ──────────────────────────────────────────────────────────────
RUN wget -q "https://github.com/grafana/loki/releases/download/v${LOKI_VERSION}/promtail-linux-${TARGETARCH}.zip" \
         -O /tmp/promtail.zip \
 && unzip -q /tmp/promtail.zip "promtail-linux-${TARGETARCH}" -d /tmp \
 && install -m 755 /tmp/promtail-linux-${TARGETARCH} /usr/local/bin/promtail \
 && rm -rf /tmp/promtail.zip /tmp/promtail-linux-${TARGETARCH}

# ── 6. InfluxDB 2.7 (server binary; init done at runtime via HTTP API) ───────
RUN wget -q "https://dl.influxdata.com/influxdb/releases/influxdb2-${INFLUXDB_VERSION}_linux_${TARGETARCH}.tar.gz" \
         -O /tmp/influxdb.tar.gz \
 && tar -xzf /tmp/influxdb.tar.gz -C /tmp \
 && INFLUXD_PATH="$(find /tmp -maxdepth 4 -type f -name influxd | head -n 1)" \
 && test -n "${INFLUXD_PATH}" \
 && install -m 755 "${INFLUXD_PATH}" /usr/local/bin/influxd \
 && test -x /usr/local/bin/influxd \
 && rm -rf /tmp/influxdb.tar.gz /tmp/influxdb2-*

# ── 7. Elasticsearch 8.x ─────────────────────────────────────────────────────
RUN ES_ARCH=$([ "${TARGETARCH}" = "amd64" ] && echo "x86_64" || echo "aarch64") \
 && wget -q "https://artifacts.elastic.co/downloads/elasticsearch/elasticsearch-${ELASTICSEARCH_VERSION}-linux-${ES_ARCH}.tar.gz" \
         -O /tmp/es.tar.gz \
 && tar -xzf /tmp/es.tar.gz -C /opt \
 && mv /opt/elasticsearch-${ELASTICSEARCH_VERSION} /opt/elasticsearch \
 && useradd -r -s /bin/false elasticsearch \
 && mkdir -p /opt/elasticsearch/data /opt/elasticsearch/logs \
 && chown -R elasticsearch:elasticsearch /opt/elasticsearch \
 && rm /tmp/es.tar.gz

# ── 8. Filebeat ──────────────────────────────────────────────────────────────
# Note: Filebeat uses "arm64" (not "aarch64") unlike Elasticsearch.
RUN FB_ARCH=$([ "${TARGETARCH}" = "amd64" ] && echo "x86_64" || echo "arm64") \
 && wget -q "https://artifacts.elastic.co/downloads/beats/filebeat/filebeat-${ELASTICSEARCH_VERSION}-linux-${FB_ARCH}.tar.gz" \
         -O /tmp/filebeat.tar.gz \
 && tar -xzf /tmp/filebeat.tar.gz -C /opt \
 && mv /opt/filebeat-${ELASTICSEARCH_VERSION}-linux-${FB_ARCH} /opt/filebeat \
 && rm /tmp/filebeat.tar.gz

# ── 9. Apache Kafka (bundles ZooKeeper; JVM → arch-independent tarball) ──────
RUN wget -q "https://archive.apache.org/dist/kafka/${KAFKA_VERSION}/kafka_${SCALA_VERSION}-${KAFKA_VERSION}.tgz" \
         -O /tmp/kafka.tgz \
 && tar -xzf /tmp/kafka.tgz -C /opt \
 && mv /opt/kafka_${SCALA_VERSION}-${KAFKA_VERSION} /opt/kafka \
 && rm /tmp/kafka.tgz

# ── 10. kafka-exporter ───────────────────────────────────────────────────────
RUN wget -q "https://github.com/danielqsj/kafka_exporter/releases/download/v${KAFKA_EXPORTER_VERSION}/kafka_exporter-${KAFKA_EXPORTER_VERSION}.linux-${TARGETARCH}.tar.gz" \
         -O /tmp/kafka-exporter.tar.gz \
 && tar -xzf /tmp/kafka-exporter.tar.gz -C /tmp \
 && install -m 755 "/tmp/kafka_exporter-${KAFKA_EXPORTER_VERSION}.linux-${TARGETARCH}/kafka_exporter" /usr/local/bin/kafka_exporter \
 && rm -rf /tmp/kafka-exporter.tar.gz "/tmp/kafka_exporter-${KAFKA_EXPORTER_VERSION}.linux-${TARGETARCH}"

# ── 11. kafka-ui fat JAR ─────────────────────────────────────────────────────
RUN wget -q "https://github.com/provectus/kafka-ui/releases/download/v${KAFKA_UI_VERSION}/kafka-ui-api-v${KAFKA_UI_VERSION}.jar" \
         -O /opt/kafka-ui.jar

# ── 12. node-exporter ────────────────────────────────────────────────────────
RUN wget -q "https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VERSION}/node_exporter-${NODE_EXPORTER_VERSION}.linux-${TARGETARCH}.tar.gz" \
         -O /tmp/node-exporter.tar.gz \
 && tar -xzf /tmp/node-exporter.tar.gz -C /tmp \
 && install -m 755 "/tmp/node_exporter-${NODE_EXPORTER_VERSION}.linux-${TARGETARCH}/node_exporter" /usr/local/bin/node_exporter \
 && rm -rf /tmp/node-exporter.tar.gz "/tmp/node_exporter-${NODE_EXPORTER_VERSION}.linux-${TARGETARCH}"

# ── 13. cadvisor ─────────────────────────────────────────────────────────────
# Needs --privileged + host mounts at runtime for full metrics.
RUN wget -q "https://github.com/google/cadvisor/releases/download/v${CADVISOR_VERSION}/cadvisor-v${CADVISOR_VERSION}-linux-${TARGETARCH}" \
         -O /usr/local/bin/cadvisor \
 && chmod 755 /usr/local/bin/cadvisor

# ── 14. Python market-bridge app ─────────────────────────────────────────────
WORKDIR /opt/market-bridge
COPY requirements.txt ./
RUN pip3 install --no-cache-dir -r requirements.txt
COPY src ./src
RUN PYTHONPATH=/opt/market-bridge/src python3 -c "import kraken_kafka_bridge.main"
WORKDIR /opt/data-generator
COPY data-generator/app.py ./app.py
COPY data-generator/elasticsearch_exporter_generator.py ./elasticsearch_exporter_generator.py
COPY data-generator/kafka_exporter_generator.py ./kafka_exporter_generator.py
RUN python3 -m py_compile /opt/data-generator/app.py
RUN python3 -m py_compile /opt/data-generator/elasticsearch_exporter_generator.py
RUN python3 -m py_compile /opt/data-generator/kafka_exporter_generator.py
WORKDIR /

# ── 15. Directory skeleton ───────────────────────────────────────────────────
RUN mkdir -p \
    /etc/prometheus \
    /prometheus \
    /var/lib/influxdb2 \
    /etc/loki \
    /loki/chunks \
    /loki/compactor \
    /etc/promtail \
    /etc/filebeat \
    /etc/kafka \
    /tmp/zookeeper \
    /tmp/kafka-logs \
    /var/lib/grafana/dashboards \
    /etc/grafana/provisioning/datasources \
    /etc/grafana/provisioning/dashboards \
    /var/log/market-bridge \
    /var/log/supervisor \
    /var/run

# ── 16. Config files (each service has its own subdirectory) ─────────────────
COPY all-in-one/prometheus/prometheus.yml       /etc/prometheus/prometheus.yml
COPY all-in-one/loki/config.yml                 /etc/loki/config.yml
COPY all-in-one/promtail/config.yml             /etc/promtail/config.yml
COPY all-in-one/filebeat/filebeat.yml           /etc/filebeat/filebeat.yml
COPY all-in-one/elasticsearch/elasticsearch.yml /opt/elasticsearch/config/elasticsearch.yml
COPY all-in-one/kafka/zookeeper.properties      /etc/kafka/zookeeper.properties
COPY all-in-one/kafka/server.properties         /etc/kafka/server.properties

# ── 17. Grafana provisioning + dashboards ────────────────────────────────────
COPY all-in-one/grafana/provisioning/datasources/datasources.yml /etc/grafana/provisioning/datasources/datasources.yaml
COPY all-in-one/grafana/provisioning/dashboards/dashboards.yml   /etc/grafana/provisioning/dashboards/dashboards.yaml
COPY all-in-one/grafana/dashboards                                /var/lib/grafana/dashboards

# ── 18. InfluxDB runtime init script (uses HTTP API, no CLI needed) ──────────
COPY all-in-one/scripts/influx-init.sh /usr/local/bin/influx-init.sh

# ── 19. Kafka startup wrapper (waits for ZooKeeper) ─────────────────────────
COPY all-in-one/scripts/start-kafka.sh /usr/local/bin/start-kafka.sh
COPY all-in-one/scripts/start-prometheus.sh /usr/local/bin/start-prometheus.sh

# ── 20. Fix permissions ──────────────────────────────────────────────────────
RUN chmod +x /usr/local/bin/influx-init.sh /usr/local/bin/start-kafka.sh /usr/local/bin/start-prometheus.sh \
 && chown -R elasticsearch:elasticsearch /opt/elasticsearch \
 && chown -R grafana:grafana /var/lib/grafana /etc/grafana

# ── 21. supervisord ──────────────────────────────────────────────────────────
COPY all-in-one/supervisord.conf /etc/supervisor/supervisord.conf

# ── Exposed ports ────────────────────────────────────────────────────────────
EXPOSE 3000
EXPOSE 9090
EXPOSE 8086
EXPOSE 3100
EXPOSE 9200
EXPOSE 19092
EXPOSE 8088
EXPOSE 9308
EXPOSE 9100
EXPOSE 8080

ENV JAVA_TOOL_OPTIONS="-Dfile.encoding=UTF-8"

CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/supervisord.conf"]
