#!/bin/bash
# Wait for ZooKeeper before starting Kafka.
set -e

echo "[start-kafka] Waiting for ZooKeeper on localhost:2181..."
until echo ruok | nc -w 2 localhost 2181 2>/dev/null | grep -q imok; do
    sleep 2
done
echo "[start-kafka] ZooKeeper is ready"

exec /opt/kafka/bin/kafka-server-start.sh /etc/kafka/server.properties
