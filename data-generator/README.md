# Data Generator

This container writes synthetic Glances-style system data into InfluxDB so the `2387_rev4.json` dashboard has historical and live data to display.

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

The generated schema matches the Glances dashboard expectations:
- bucket: `glances`
- measurements: `load`, `processcount`, `cpu`, `mem`, `network`, `memswap`, `diskio`, `fs`, `sensors`, `docker`
- tags: `hostname`, `interface_name`, `disk_name`, `name`, `label`, `mnt_point`
