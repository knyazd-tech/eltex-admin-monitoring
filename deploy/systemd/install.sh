#!/usr/bin/env bash

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this installer as root."
    exit 1
fi

PackageRoot="$(
    cd \
        "$(dirname "${BASH_SOURCE[0]}")/../.." \
        && pwd
)"

if ! getent group \
    eltex-exporter \
    >/dev/null
then
    groupadd \
        --system \
        eltex-exporter
fi

if ! id \
    eltex-exporter \
    >/dev/null 2>&1
then
    useradd \
        --system \
        --gid eltex-exporter \
        --home-dir /nonexistent \
        --shell /usr/sbin/nologin \
        eltex-exporter
fi

install \
    --directory \
    --owner=root \
    --group=root \
    --mode=0755 \
    /opt/eltex-exporter

install \
    --owner=root \
    --group=root \
    --mode=0755 \
    "$PackageRoot/exporter/eltex_exporter.py" \
    /opt/eltex-exporter/eltex_exporter.py

install \
    --directory \
    --owner=root \
    --group=eltex-exporter \
    --mode=0750 \
    /etc/eltex-exporter

if [ ! -f /etc/eltex-exporter/credentials ]; then
    install \
        --owner=root \
        --group=eltex-exporter \
        --mode=0640 \
        "$PackageRoot/.env.example" \
        /etc/eltex-exporter/credentials

    echo
    echo "Edit /etc/eltex-exporter/credentials"
    echo "before starting the service."
fi

install \
    --owner=root \
    --group=root \
    --mode=0644 \
    "$PackageRoot/deploy/systemd/eltex-exporter.service" \
    /etc/systemd/system/eltex-exporter.service

systemctl daemon-reload

echo
echo "Installation complete."
echo "After configuring credentials, run:"
echo "  systemctl enable --now eltex-exporter"
