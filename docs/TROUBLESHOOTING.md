# Troubleshooting

## Exporter does not start

Check required environment variables and base64 formatting:

```sh
systemctl status eltex-exporter
journalctl -u eltex-exporter -n 100 --no-pager
```

## Health works but metrics are stale

Inspect:

- `eltex_collection_success`
- `eltex_collection_errors_total`
- `eltex_last_success_timestamp_seconds`
- `eltex_collection_duration_seconds`

A device firmware update can change JSON fields, API operation
names, HTML paths, or localized table labels.

## Authentication failure

Verify the management URL and credentials from the exporter
host. Do not paste credentials into command history or issue
reports.

## Prometheus target is down

Check routing, firewall policy, the listen address, port 9824,
and `/healthz`. Prefer binding the exporter to a management
address rather than all interfaces.

## Missing legacy metrics

Confirm that the device UI language and firmware still expose
the expected status pages. Legacy collection parses localized
HTML tables and is therefore more firmware-sensitive than JSON
collection.
