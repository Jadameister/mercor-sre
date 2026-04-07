FROM python:3.11-slim

WORKDIR /app

COPY data-generator/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY data-generator/app.py ./app.py

ENV INFLUXDB_URL=http://host.docker.internal:8086
ENV INFLUXDB_TOKEN=marketdata-token
ENV INFLUXDB_ORG=test-org
ENV INFLUXDB_BUCKET=glances
ENV BACKFILL_DAYS=7
ENV STEP_SECONDS=60
ENV RUN_FOREVER=true
ENV HOSTS=edge-01,edge-02
ENV CONTAINERS=nginx,redis,postgres,worker
ENV INTERFACES=eth0,eth1
ENV DISKS=sda,sdb

CMD ["python", "/app/app.py"]
