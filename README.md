# Eltex Admin Monitoring

A standalone, read-only Prometheus exporter and monitoring
package for supported Eltex optical network terminals and
gateways.

The package was validated against the web management API and
HTML status pages used by the Eltex NTU-RG-5420G-Wac family.
Firmware variants may expose different operations, field names,
or localized HTML labels.

## Components

- Standard-library Python exporter.
- 46 Prometheus metric families.
- Grafana dashboard.
- Prometheus alert rules.
- Prometheus scrape example.
- Hardened systemd service.
- Docker and Compose deployment examples.

## Safety model

The exporter performs status and statistics reads. It does not
provide an API for changing device configuration. Use a
dedicated least-privilege account if the device firmware
supports one.

The device credentials are supplied through environment
variables. Base64 encoding is transport encoding, not
encryption. Protect the environment file with filesystem
permissions and restrict access to port 9824.

## Quick start

Copy the example environment file:

```sh
cp .env.example .env
```

Set `ELTEX_BASE_URL`, `ELTEX_USERNAME_B64`, and
`ELTEX_PASSWORD_B64`.

Run with Compose:

```sh
docker compose up --build -d
curl http://127.0.0.1:9824/healthz
curl http://127.0.0.1:9824/metrics
```

For systemd deployment:

```sh
sudo deploy/systemd/install.sh
sudo editor /etc/eltex-exporter/credentials
sudo systemctl enable --now eltex-exporter
```

## Prometheus

Copy the scrape job from `prometheus/eltex-scrape.yml` into
your Prometheus configuration, then check it with `promtool`.

## Grafana

Import `grafana/dashboards/eltex-router.json` and select your
Prometheus datasource.

## Compatibility

The exporter combines newer JSON API calls with legacy HTML
status pages. Collection is split into fast and legacy loops.
Use `eltex_collection_success` and
`eltex_last_success_timestamp_seconds` to detect partial
collection failures.

## Documentation

- `docs/METRICS.md`
- `docs/ALERTS.md`
- `docs/TROUBLESHOOTING.md`
- `SECURITY.md`

## License

Apache License 2.0.
