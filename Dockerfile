FROM python:3.12-alpine

RUN addgroup \
        -S exporter \
    && adduser \
        -S \
        -D \
        -H \
        -G exporter \
        exporter

WORKDIR /app

COPY \
    --chown=exporter:exporter \
    exporter/eltex_exporter.py \
    /app/eltex_exporter.py

USER exporter

EXPOSE 9824

ENTRYPOINT \
    ["python3", "/app/eltex_exporter.py"]
