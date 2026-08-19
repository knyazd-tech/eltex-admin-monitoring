#!/usr/bin/env python3

import base64
import hashlib
import html
import http.cookiejar
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer


def required_env(name):
    value = os.environ.get(name, "").strip()

    if not value:
        raise RuntimeError(
            f"required environment variable is missing: {name}"
        )

    return value


BASE = required_env(
    "ELTEX_BASE_URL"
).rstrip("/")

USERNAME = base64.b64decode(
    required_env(
        "ELTEX_USERNAME_B64"
    ),
    validate=True,
).decode("utf-8")

PASSWORD = base64.b64decode(
    required_env(
        "ELTEX_PASSWORD_B64"
    ),
    validate=True,
).decode("utf-8")

LISTEN_ADDRESS = os.environ.get(
    "ELTEX_LISTEN_ADDRESS",
    "127.0.0.1",
)

LISTEN_PORT = int(
    os.environ.get(
        "ELTEX_LISTEN_PORT",
        "9824",
    )
)

FAST_INTERVAL = int(
    os.environ.get(
        "ELTEX_FAST_INTERVAL",
        "30",
    )
)

LEGACY_INTERVAL = int(
    os.environ.get(
        "ELTEX_LEGACY_INTERVAL",
        "60",
    )
)

REQUEST_TIMEOUT = int(
    os.environ.get(
        "ELTEX_REQUEST_TIMEOUT",
        "20",
    )
)


def md5(value):
    return hashlib.md5(
        value.encode("utf-8")
    ).hexdigest()


def metric_name(value):
    value = re.sub(
        r"[^a-zA-Z0-9_:]",
        "_",
        value,
    )

    if not re.match(
        r"[a-zA-Z_:]",
        value,
    ):
        value = "_" + value

    return value


def label_escape(value):
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace('"', '\\"')
    )


def labels_text(labels):
    if not labels:
        return ""

    parts = [
        f'{metric_name(key)}="{label_escape(value)}"'
        for key, value in sorted(
            labels.items()
        )
    ]

    return "{" + ",".join(parts) + "}"


def metric(
    lines,
    name,
    value,
    labels=None,
    help_text=None,
    metric_type=None,
):
    if help_text:
        lines.append(
            f"# HELP {name} {help_text}"
        )

    if metric_type:
        lines.append(
            f"# TYPE {name} {metric_type}"
        )

    lines.append(
        f"{name}{labels_text(labels)} {value}"
    )


def number(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    match = re.search(
        r"-?\d+(?:\.\d+)?",
        str(value).replace(",", "."),
    )

    if not match:
        return None

    return float(match.group(0))


def integer(value):
    converted = number(value)

    if converted is None:
        return None

    return int(converted)


def counter(value):
    converted = integer(value)

    if converted is None:
        return None

    if converted < 0:
        converted += 2 ** 32

    return converted


def state_up(value):
    lowered = str(value).strip().lower()

    return 1 if lowered in {
        "up",
        "connected",
        "enabled",
        "active",
        "o5",
        "1",
        "true",
    } else 0


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(
            convert_charrefs=True
        )

        self.tables = []
        self.table = None
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.table = []
            self.tables.append(self.table)

        elif (
            tag == "tr"
            and self.table is not None
        ):
            self.row = []
            self.table.append(self.row)

        elif (
            tag in ("td", "th")
            and self.row is not None
        ):
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if (
            tag in ("td", "th")
            and self.cell is not None
            and self.row is not None
        ):
            self.row.append(
                " ".join(
                    html.unescape(
                        "".join(self.cell)
                    ).split()
                )
            )
            self.cell = None

        elif tag == "tr":
            self.row = None

        elif tag == "table":
            self.table = None


class EltexClient:
    def __init__(self):
        self.cookies = (
            http.cookiejar.CookieJar()
        )

        self.opener = (
            urllib.request.build_opener(
                urllib.request
                .HTTPCookieProcessor(
                    self.cookies
                )
            )
        )

        self.opener.addheaders = [
            (
                "User-Agent",
                "Eltex-Prometheus-Exporter/1.0",
            ),
            (
                "Accept-Language",
                "ru-RU,ru;q=0.9,en;q=0.8",
            ),
        ]

        self.authenticated = False

    def request(
        self,
        url,
        method="GET",
        body=None,
        headers=None,
    ):
        request = urllib.request.Request(
            url,
            data=body,
            method=method,
            headers=dict(headers or {}),
        )

        try:
            with self.opener.open(
                request,
                timeout=REQUEST_TIMEOUT,
            ) as response:
                return {
                    "status": getattr(
                        response,
                        "status",
                        200,
                    ),
                    "headers": response.headers,
                    "body": response.read(
                        16 * 1024 * 1024
                    ),
                    "url": response.geturl(),
                }

        except urllib.error.HTTPError as error:
            return {
                "status": error.code,
                "headers": error.headers,
                "body": error.read(
                    16 * 1024 * 1024
                ),
                "url": error.geturl(),
            }

    def parse_challenge(self, value):
        if not value:
            raise RuntimeError(
                "XDigest challenge missing"
            )

        scheme, separator, params = (
            value.partition(" ")
        )

        if not separator:
            raise RuntimeError(
                "invalid XDigest challenge"
            )

        result = {
            "scheme": scheme,
        }

        pattern = re.compile(
            r"""([A-Za-z][A-Za-z0-9_-]*)"""
            r"""\s*=\s*"""
            r"""(?:"([^"]*)"|([^,\s]+))"""
        )

        for match in pattern.finditer(params):
            result[
                match.group(1).lower()
            ] = (
                match.group(2)
                if match.group(2) is not None
                else match.group(3)
            )

        return result

    def signin(self):
        url = (
            BASE
            + "/server/api.lua"
            + "?operation=signin"
        )

        common_headers = {
            "Content-Type": (
                "application/json"
            ),
            "Accept": (
                "application/json,*/*"
            ),
            "Origin": BASE,
            "Referer": (
                BASE
                + "/client/signin.html"
            ),
        }

        first = self.request(
            url,
            method="POST",
            body=b"",
            headers=common_headers,
        )

        challenge = self.parse_challenge(
            first["headers"].get(
                "WWW-Authenticate"
            )
        )

        realm = challenge["realm"]
        nonce = challenge["nonce"]
        opaque = challenge.get(
            "opaque",
            "",
        )
        qop = "auth"
        nc = "00000002"
        cnonce = secrets.token_hex(8)

        ha1 = md5(
            f"{USERNAME}:{realm}:{PASSWORD}"
        )
        ha2 = md5(
            f"POST:{url}"
        )
        digest = md5(
            f"{ha1}:{nonce}:{nc}:"
            f"{cnonce}:{qop}:{ha2}"
        )

        parts = [
            (
                f'{challenge["scheme"]} '
                f'username="{USERNAME}"'
            ),
            f'realm="{realm}"',
            f'nonce="{nonce}"',
            f'uri="{url}"',
            f'response="{digest}"',
        ]

        if opaque:
            parts.append(
                f'opaque="{opaque}"'
            )

        parts.extend(
            [
                f"qop={qop}",
                f"nc={nc}",
                f'cnonce="{cnonce}"',
            ]
        )

        headers = dict(common_headers)
        headers["Authorization"] = (
            ", ".join(parts)
        )

        second = self.request(
            url,
            method="POST",
            body=b"",
            headers=headers,
        )

        text = second["body"].decode(
            "utf-8",
            errors="replace",
        )

        result = json.loads(text)

        if (
            second["status"] != 200
            or result.get("status") != 0
            or result.get(
                "data",
                {},
            ).get("success") is not True
        ):
            raise RuntimeError(
                "Eltex signin failed"
            )

        self.authenticated = True

        self.request(
            BASE + "/client/index.html",
            method="GET",
            headers={
                "Accept": "text/html,*/*",
                "Referer": (
                    BASE
                    + "/client/signin.html"
                ),
            },
        )

    def ensure_signin(self):
        if not self.authenticated:
            self.signin()

    def gsend(self, operation):
        self.ensure_signin()

        envelope = {
            "action": operation,
            "post_data": {},
        }

        body = urllib.parse.urlencode(
            {
                "post_data": json.dumps(
                    envelope,
                    separators=(",", ":"),
                ),
            }
        ).encode("utf-8")

        response = self.request(
            (
                BASE
                + "/server/api.lua"
                + "?operation="
                + operation
            ),
            method="POST",
            body=body,
            headers={
                "Content-Type": (
                    "application/"
                    "x-www-form-urlencoded; "
                    "charset=UTF-8"
                ),
                "X-Requested-With": (
                    "XMLHttpRequest"
                ),
                "Accept": (
                    "text/javascript, "
                    "text/html, "
                    "application/xml, "
                    "text/xml, */*"
                ),
                "Origin": BASE,
                "Referer": (
                    BASE
                    + "/client/index.html"
                ),
            },
        )

        text = response["body"].decode(
            "utf-8",
            errors="replace",
        )

        if response["status"] != 200:
            self.authenticated = False
            raise RuntimeError(
                f"{operation}: "
                f"HTTP {response['status']}"
            )

        result = json.loads(text)

        if result.get("status") != 0:
            self.authenticated = False
            raise RuntimeError(
                f"{operation}: "
                f"API status "
                f"{result.get('status')}"
            )

        return result.get("data")

    def get_html(self, path):
        self.ensure_signin()

        response = self.request(
            urllib.parse.urljoin(
                BASE,
                path,
            ),
            method="GET",
            headers={
                "Accept": (
                    "text/html,"
                    "application/xhtml+xml,"
                    "application/xml;q=0.9,"
                    "*/*;q=0.8"
                ),
                "Referer": (
                    BASE
                    + "/client/index.html"
                ),
            },
        )

        if response["status"] != 200:
            self.authenticated = False
            raise RuntimeError(
                f"{path}: "
                f"HTTP {response['status']}"
            )

        parser = TableParser()
        parser.feed(
            response["body"].decode(
                "utf-8",
                errors="replace",
            )
        )

        return parser.tables


class ExporterState:
    def __init__(self):
        self.lock = threading.Lock()
        self.collector_metrics = {
            "fast": [],
            "legacy": [],
        }
        self.collector_success = {
            "fast": 0,
            "legacy": 0,
        }
        self.last_success = {
            "fast": 0,
            "legacy": 0,
        }
        self.duration = {
            "fast": 0,
            "legacy": 0,
        }
        self.errors = {
            "fast": 0,
            "legacy": 0,
        }

    def update(
        self,
        collector,
        success,
        duration,
        lines=None,
    ):
        with self.lock:
            self.collector_success[
                collector
            ] = 1 if success else 0

            self.duration[
                collector
            ] = duration

            if success:
                self.last_success[
                    collector
                ] = int(time.time())

                if lines is not None:
                    self.collector_metrics[
                        collector
                    ] = lines
            else:
                self.errors[
                    collector
                ] += 1

    def render(self):
        with self.lock:
            lines = [
                "# HELP eltex_up "
                "Eltex exporter collection status",
                "# TYPE eltex_up gauge",
                (
                    "eltex_up "
                    + str(
                        min(
                            self.collector_success[
                                "fast"
                            ],
                            self.collector_success[
                                "legacy"
                            ],
                        )
                    )
                ),
            ]

            for collector in (
                "fast",
                "legacy",
            ):
                labels = labels_text(
                    {
                        "collector": collector,
                    }
                )

                lines.extend(
                    [
                        (
                            "eltex_"
                            "collection_success"
                            f"{labels} "
                            f"{self.collector_success[collector]}"
                        ),
                        (
                            "eltex_"
                            "collection_duration_seconds"
                            f"{labels} "
                            f"{self.duration[collector]:.6f}"
                        ),
                        (
                            "eltex_"
                            "last_success_timestamp_seconds"
                            f"{labels} "
                            f"{self.last_success[collector]}"
                        ),
                        (
                            "eltex_"
                            "collection_errors_total"
                            f"{labels} "
                            f"{self.errors[collector]}"
                        ),
                    ]
                )

                lines.extend(
                    self.collector_metrics[
                        collector
                    ]
                )

            return (
                "\n".join(lines)
                + "\n"
            ).encode("utf-8")


STATE = ExporterState()
CLIENT = EltexClient()


def fast_metrics():
    data = {}

    for operation in (
        "about",
        "device_status",
        "dynamic_info",
        "get_statistics",
        "get_wan_ifaces_status",
        "get_dhcp",
        "get_omci_vlan",
    ):
        data[operation] = (
            CLIENT.gsend(operation)
        )

    lines = []
    about = data["about"] or {}
    device = data["device_status"] or {}
    dynamic = data["dynamic_info"] or {}

    metric(
        lines,
        "eltex_info",
        1,
        {
            "board": about.get(
                "Board",
                "",
            ),
            "firmware": about.get(
                "Firmware",
                "",
            ),
            "hw_revision": about.get(
                "HwRev",
                "",
            ),
        },
    )

    cpu = number(
        device.get("cpuUsage")
    )

    if cpu is None:
        cpu = number(
            dynamic.get("CpuActive")
        )

    if cpu is not None:
        metric(
            lines,
            "eltex_cpu_usage_percent",
            cpu,
        )

    memory_total_kib = number(
        device.get("memoryTotal")
    )
    memory_free_kib = number(
        device.get("memoryFree")
    )

    if memory_total_kib is not None:
        metric(
            lines,
            "eltex_memory_total_bytes",
            int(
                memory_total_kib * 1024
            ),
        )

    if memory_free_kib is not None:
        metric(
            lines,
            "eltex_memory_free_bytes",
            int(
                memory_free_kib * 1024
            ),
        )

    if (
        memory_total_kib is not None
        and memory_free_kib is not None
        and memory_total_kib > 0
    ):
        used = (
            memory_total_kib
            - memory_free_kib
        )

        metric(
            lines,
            "eltex_memory_used_bytes",
            int(used * 1024),
        )

        metric(
            lines,
            "eltex_memory_usage_percent",
            (
                100
                * used
                / memory_total_kib
            ),
        )

    uptime = number(
        dynamic.get("UpTime")
    )

    if uptime is not None:
        metric(
            lines,
            "eltex_uptime_seconds",
            int(uptime),
        )

    metric(
        lines,
        "eltex_bosa_calibrated",
        (
            1
            if about.get(
                "BosaIsCalibrated"
            )
            else 0
        ),
    )

    for item in (
        data["get_statistics"]
        or []
    ):
        interface = str(
            item.get("name", "unknown")
        )

        for direction_key, direction in (
            ("RX", "receive"),
            ("TX", "transmit"),
        ):
            counters = (
                item.get(direction_key)
                or {}
            )

            for source, suffix in (
                ("bytes", "bytes_total"),
                (
                    "packets",
                    "packets_total",
                ),
            ):
                value = counter(
                    counters.get(source)
                )

                if value is not None:
                    metric(
                        lines,
                        (
                            "eltex_"
                            f"interface_{suffix}"
                        ),
                        value,
                        {
                            "interface": (
                                interface
                            ),
                            "direction": (
                                direction
                            ),
                        },
                    )

        if "state" in item:
            metric(
                lines,
                "eltex_interface_up",
                state_up(
                    item.get("state")
                ),
                {
                    "interface": interface,
                    "mode": item.get(
                        "cmode",
                        "",
                    ),
                },
            )

    for item in (
        data[
            "get_wan_ifaces_status"
        ]
        or []
    ):
        metric(
            lines,
            "eltex_wan_up",
            state_up(
                item.get("strStatus")
            ),
            {
                "interface": item.get(
                    "ifname",
                    "unknown",
                ),
                "protocol": item.get(
                    "protocol",
                    "",
                ),
                "mode": item.get(
                    "cmode",
                    "",
                ),
            },
        )

    omci = data["get_omci_vlan"] or {}

    for item in omci.get(
        "table",
        [],
    ):
        metric(
            lines,
            "eltex_omci_vlan_info",
            1,
            {
                "gem": item.get(
                    "gem",
                    "",
                ),
                "vlan": item.get(
                    "vlan",
                    "",
                ),
            },
        )

    return lines


def find_value(tables, label):
    for table in tables:
        for row in table:
            if (
                len(row) >= 2
                and row[0].strip()
                == label
            ):
                return row[1]

    return None


def legacy_metrics():
    lines = []

    pon = CLIENT.get_html(
        "/admin/status_pon.asp"
    )

    optical = {
        "Температура": (
            "eltex_pon_temperature_celsius"
        ),
        "Напряжение": (
            "eltex_pon_voltage_volts"
        ),
        "Мощность передатчика": (
            "eltex_pon_tx_power_dbm"
        ),
        "Чувствительность приёмника": (
            "eltex_pon_rx_power_dbm"
        ),
        "Ток смещения": (
            "eltex_pon_bias_current_milliamps"
        ),
    }

    for label, name in optical.items():
        value = number(
            find_value(pon, label)
        )

        if value is not None:
            metric(
                lines,
                name,
                value,
            )

    onu_state = find_value(
        pon,
        "Статус ONU",
    )

    if onu_state is not None:
        metric(
            lines,
            "eltex_pon_onu_state_info",
            1,
            {
                "state": onu_state,
            },
        )

        metric(
            lines,
            "eltex_pon_operational",
            (
                1
                if str(
                    onu_state
                ).strip().upper() == "O5"
                else 0
            ),
        )

    lan = CLIENT.get_html(
        "/admin/lan_port_status.asp"
    )

    for table in lan:
        for row in table:
            if (
                len(row) < 2
                or not re.match(
                    r"^(?:LAN\d+|wlan\d+)$",
                    row[0],
                    re.IGNORECASE,
                )
            ):
                continue

            interface = row[0]
            status = row[1]

            metric(
                lines,
                "eltex_port_up",
                (
                    1
                    if status.lower().startswith(
                        "up"
                    )
                    else 0
                ),
                {
                    "interface": interface,
                },
            )

            speed_match = re.search(
                r"(\d+)M",
                status,
                re.IGNORECASE,
            )

            if speed_match:
                metric(
                    lines,
                    "eltex_port_speed_bits",
                    int(
                        speed_match.group(1)
                    )
                    * 1_000_000,
                    {
                        "interface": interface,
                    },
                )

            if (
                "full" in status.lower()
                or "half" in status.lower()
            ):
                metric(
                    lines,
                    "eltex_port_full_duplex",
                    (
                        1
                        if "full" in status.lower()
                        else 0
                    ),
                    {
                        "interface": interface,
                    },
                )

    interface_stats = CLIENT.get_html(
        "/stats_user.asp"
    )

    for table in interface_stats:
        if not table:
            continue

        header = table[0]

        if (
            len(header) < 7
            or header[0] != "Интерфейс"
        ):
            continue

        for row in table[1:]:
            if len(row) < 7:
                continue

            interface = row[0]

            values = {
                (
                    "receive",
                    "packets_total",
                ): row[1],
                (
                    "receive",
                    "errors_total",
                ): row[2],
                (
                    "receive",
                    "drops_total",
                ): row[3],
                (
                    "transmit",
                    "packets_total",
                ): row[4],
                (
                    "transmit",
                    "errors_total",
                ): row[5],
                (
                    "transmit",
                    "drops_total",
                ): row[6],
            }

            for (
                direction,
                suffix,
            ), raw_value in values.items():
                parsed = counter(raw_value)

                if parsed is None:
                    continue

                metric(
                    lines,
                    (
                        "eltex_"
                        f"interface_{suffix}"
                    ),
                    parsed,
                    {
                        "interface": (
                            interface
                        ),
                        "direction": (
                            direction
                        ),
                    },
                )

    pon_stats = CLIENT.get_html(
        "/admin/pon-stats.asp"
    )

    mappings = {
        "Отправлено байт": (
            "eltex_pon_transmit_bytes_total"
        ),
        "Получено байт": (
            "eltex_pon_receive_bytes_total"
        ),
        "Пакеты, отправленные": (
            "eltex_pon_transmit_packets_total"
        ),
        "Получено пакетов": (
            "eltex_pon_receive_packets_total"
        ),
        "Отправлено пакетов Unicast": (
            "eltex_pon_transmit_unicast_packets_total"
        ),
        "Получено пакетов Unicast": (
            "eltex_pon_receive_unicast_packets_total"
        ),
        "Отправлено пакетов Multicast": (
            "eltex_pon_transmit_multicast_packets_total"
        ),
        "Получено пакетов Multicast": (
            "eltex_pon_receive_multicast_packets_total"
        ),
        "Отправлено пакетов Broadcast": (
            "eltex_pon_transmit_broadcast_packets_total"
        ),
        "Получено пакетов Broadcast": (
            "eltex_pon_receive_broadcast_packets_total"
        ),
        "FEC ошибки": (
            "eltex_pon_fec_errors_total"
        ),
        "Ошибки HEC": (
            "eltex_pon_hec_errors_total"
        ),
        "Пакеты, отброшенные": (
            "eltex_pon_dropped_packets_total"
        ),
        "Отправлено пакетов c задержкой": (
            "eltex_pon_transmit_delayed_packets_total"
        ),
        "Получено пакетов c задержкой": (
            "eltex_pon_receive_delayed_packets_total"
        ),
    }

    for label, name in mappings.items():
        value = counter(
            find_value(
                pon_stats,
                label,
            )
        )

        if value is not None:
            metric(
                lines,
                name,
                value,
            )

    arp = CLIENT.get_html(
        "/arptable.asp"
    )

    arp_entries = 0

    for table in arp:
        for row in table:
            if (
                row
                and re.fullmatch(
                    r"\d{1,3}(?:\.\d{1,3}){3}",
                    row[0],
                )
            ):
                arp_entries += 1

    metric(
        lines,
        "eltex_arp_entries",
        arp_entries,
    )

    return lines


def collector_loop():
    next_legacy = 0

    while True:
        fast_started = time.monotonic()

        try:
            lines = fast_metrics()
            STATE.update(
                "fast",
                True,
                (
                    time.monotonic()
                    - fast_started
                ),
                lines,
            )

        except Exception:
            CLIENT.authenticated = False
            STATE.update(
                "fast",
                False,
                (
                    time.monotonic()
                    - fast_started
                ),
            )

        now = time.monotonic()

        if now >= next_legacy:
            legacy_started = (
                time.monotonic()
            )

            try:
                lines = legacy_metrics()
                STATE.update(
                    "legacy",
                    True,
                    (
                        time.monotonic()
                        - legacy_started
                    ),
                    lines,
                )

            except Exception:
                CLIENT.authenticated = False
                STATE.update(
                    "legacy",
                    False,
                    (
                        time.monotonic()
                        - legacy_started
                    ),
                )

            next_legacy = (
                time.monotonic()
                + LEGACY_INTERVAL
            )

        time.sleep(FAST_INTERVAL)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/metrics":
            body = STATE.render()

            self.send_response(200)
            self.send_header(
                "Content-Type",
                (
                    "text/plain; "
                    "version=0.0.4; "
                    "charset=utf-8"
                ),
            )
            self.send_header(
                "Content-Length",
                str(len(body)),
            )
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/healthz":
            body = b"ok\n"

            self.send_response(200)
            self.send_header(
                "Content-Type",
                "text/plain",
            )
            self.send_header(
                "Content-Length",
                str(len(body)),
            )
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        return


def main():
    thread = threading.Thread(
        target=collector_loop,
        daemon=True,
    )
    thread.start()

    server = ThreadingHTTPServer(
        (
            LISTEN_ADDRESS,
            LISTEN_PORT,
        ),
        Handler,
    )

    server.serve_forever()


if __name__ == "__main__":
    main()
