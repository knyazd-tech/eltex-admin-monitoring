#!/usr/bin/env python3

import ipaddress
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]

private_word = "sew" + "ing"
old_namespace = (
    private_word
    + "_eltex_"
)

required = [
    ".env.example",
    "README.md",
    "SECURITY.md",
    "CHANGELOG.md",
    "LICENSE",
    "Dockerfile",
    "compose.yaml",
    "exporter/eltex_exporter.py",
    "deploy/systemd/eltex-exporter.service",
    "deploy/systemd/install.sh",
    "prometheus/eltex-scrape.yml",
    "prometheus/rules/eltex-alerts.yml",
    "grafana/dashboards/eltex-router.json",
    "docs/METRICS.md",
    "docs/ALERTS.md",
    "docs/TROUBLESHOOTING.md",
    "docs/metric-registry.json",
]

issues = []
metric_names = set()

for relative in required:
    if not (root / relative).is_file():
        issues.append(
            f"missing file: {relative}"
        )

for path in root.rglob("*"):
    if not path.is_file():
        continue

    if ".git" in path.parts:
        continue

    if path.name in {
        "LICENSE",
        "Dockerfile",
    }:
        eligible = True
    else:
        eligible = path.suffix.lower() in {
            "",
            ".py",
            ".md",
            ".json",
            ".yml",
            ".yaml",
            ".sh",
            ".example",
        }

    if not eligible:
        continue

    text = path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    relative = path.relative_to(root)
    lowered = text.lower()

    if old_namespace in lowered:
        issues.append(
            f"old namespace: {relative}"
        )

    private_branding = re.compile(
        re.escape(private_word)
        + r"(?:[_-]| volume|\b)",
        re.IGNORECASE,
    )

    if private_branding.search(text):
        issues.append(
            f"private branding: {relative}"
        )

    if re.search(
        r"\bgh[oprsu]_[A-Za-z0-9]{20,}\b",
        text,
    ):
        issues.append(
            f"GitHub token: {relative}"
        )

    if re.search(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        text,
    ):
        issues.append(
            f"private key: {relative}"
        )

    if re.search(
        r"://[^/\s:@]+:[^/\s@]+@",
        text,
    ):
        issues.append(
            f"credential URL: {relative}"
        )

    for candidate in re.findall(
        r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        text,
    ):
        try:
            address = ipaddress.ip_address(
                candidate
            )
        except ValueError:
            continue

        if (
            address.is_private
            and not address.is_loopback
            and str(address) != "0.0.0.0"
        ):
            issues.append(
                f"private IP {candidate}: {relative}"
            )

    metric_names.update(
        re.findall(
            r"\beltex_[A-Za-z0-9_:]+",
            text,
        )
    )

dashboard_path = (
    root
    / "grafana/dashboards/eltex-router.json"
)

dashboard = json.loads(
    dashboard_path.read_text(
        encoding="utf-8",
    )
)

registry_path = (
    root
    / "docs/metric-registry.json"
)

registry = json.loads(
    registry_path.read_text(
        encoding="utf-8",
    )
)

registry_names = {
    row["metric"]
    for row in registry
}

if len(registry_names) != 46:
    issues.append(
        "metric registry does not contain 46 unique metrics"
    )

invalid_registry_names = {
    name
    for name in registry_names
    if not name.startswith("eltex_")
}

for name in sorted(invalid_registry_names):
    issues.append(
        f"invalid registry namespace: {name}"
    )

dashboard_text = json.dumps(
    dashboard,
    ensure_ascii=False,
)

dashboard_metrics = set(
    re.findall(
        r"\beltex_[A-Za-z0-9_:]+",
        dashboard_text,
    )
)

missing_dashboard_metrics = (
    registry_names
    - dashboard_metrics
)

for name in sorted(
    missing_dashboard_metrics
):
    issues.append(
        f"dashboard missing metric: {name}"
    )

if len(metric_names) < 46:
    issues.append(
        "fewer than 46 Eltex metrics detected"
    )

if issues:
    print(
        "Validation issues:",
        len(set(issues)),
    )

    for issue in sorted(set(issues)):
        print("-", issue)

    raise SystemExit(1)

print("Required files:", len(required))
print("Registry metrics:", len(registry_names))
print("Dashboard metrics:", len(dashboard_metrics))
print("Detected metric references:", len(metric_names))
print("Private identifiers: 0")
print("PACKAGE VALIDATION: PASS")
