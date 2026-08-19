# Contributing

## Scope

Contributions should preserve the exporter’s read-only safety
model and the generic `eltex_*` metric namespace.

Do not submit:

- Device credentials or session cookies.
- Private management addresses.
- Serial numbers or configuration backups.
- Captured proprietary firmware assets.
- Organization-specific labels or dashboard URLs.

## Local validation

Run:

```sh
python3 -m py_compile exporter/eltex_exporter.py
python3 tests/validate_package.py

docker run \
  --rm \
  --entrypoint /bin/promtool \
  --volume "$PWD/prometheus/rules:/rules:ro" \
  prom/prometheus:v3.13.2 \
  check rules \
  /rules/eltex-alerts.yml

cp .env.example .env
docker compose config --quiet
rm .env
```

## Pull requests

Describe:

- Device model and firmware family.
- Whether JSON API or legacy HTML collection changed.
- Added, removed, or renamed metrics.
- Dashboard and alert-rule impact.
- Validation commands performed.

Keep commits focused and do not include generated device UI
assets.
