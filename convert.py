#!/usr/bin/env python3

import base64
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

SOURCE_URL = "https://raw.githubusercontent.com/free-nodes/v2rayfree/main/sub"
OUTPUT_FILE = Path("clash.yaml")
TEST_URL = "https://www.gstatic.com/generate_204"


def decode_base64_text(value: str) -> str:
    value = urllib.parse.unquote(value.strip())
    value = "".join(value.split())
    value = value.replace("-", "+").replace("_", "/")
    value += "=" * ((4 - len(value) % 4) % 4)
    return base64.b64decode(value).decode("utf-8-sig")


def decode_subscription(raw: str) -> str:
    text = raw.strip()

    if "://" in text:
        return text

    return decode_base64_text(text)


def split_host_port(value: str):
    value = value.strip()

    if value.startswith("["):
        end = value.find("]")
        if end == -1 or end + 1 >= len(value) or value[end + 1] != ":":
            raise ValueError(f"Invalid host/port: {value}")
        return value[1:end], int(value[end + 2:])

    host, port = value.rsplit(":", 1)
    return host, int(port)


def parse_ss(uri: str, index: int):
    without_fragment, _, fragment = uri.partition("#")
    name = urllib.parse.unquote(fragment) if fragment else f"SS-{index:03d}"

    body = without_fragment[len("ss://"):]
    body, _, query = body.partition("?")

    if "@" in body:
        encoded_userinfo, server_part = body.rsplit("@", 1)
        credentials = decode_base64_text(encoded_userinfo)
    else:
        decoded = decode_base64_text(body)
        credentials, server_part = decoded.rsplit("@", 1)

    method, password = credentials.split(":", 1)
    server, port = split_host_port(server_part)

    if query:
        params = urllib.parse.parse_qs(query)
        if params.get("plugin"):
            raise ValueError("SS plugin nodes are not supported by this simple converter")

    return {
        "name": name,
        "type": "ss",
        "server": server,
        "port": port,
        "cipher": method,
        "password": password,
        "udp": True,
    }


def make_unique_names(proxies):
    counts = {}

    for proxy in proxies:
        base_name = proxy["name"].strip() or "Unnamed"
        counts[base_name] = counts.get(base_name, 0) + 1

        if counts[base_name] == 1:
            proxy["name"] = base_name
        else:
            proxy["name"] = f"{base_name} ({counts[base_name]})"


def main():
    request = urllib.request.Request(
        SOURCE_URL,
        headers={"User-Agent": "clash-free-nodes-converter/1.0"},
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode("utf-8-sig")

    decoded = decode_subscription(raw)
    uris = [line.strip() for line in decoded.splitlines() if line.strip()]

    proxies = []
    skipped = []

    for index, uri in enumerate(uris, 1):
        if not uri.startswith("ss://"):
            skipped.append((index, "unsupported protocol"))
            continue

        try:
            proxies.append(parse_ss(uri, index))
        except Exception as exc:
            skipped.append((index, str(exc)))

    if not proxies:
        raise RuntimeError(
            "No supported Shadowsocks nodes were found in the upstream subscription."
        )

    make_unique_names(proxies)
    names = [proxy["name"] for proxy in proxies]

    config = {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "info",
        "ipv6": True,
        "proxies": proxies,
        "proxy-groups": [
            {
                "name": "FREE-NODES",
                "type": "select",
                "proxies": ["AUTO", "DIRECT", *names],
            },
            {
                "name": "AUTO",
                "type": "url-test",
                "url": TEST_URL,
                "interval": 300,
                "tolerance": 50,
                "proxies": names,
            },
        ],
        "rules": [
            "MATCH,FREE-NODES",
        ],
    }

    OUTPUT_FILE.write_text(
        yaml.safe_dump(
            config,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        ),
        encoding="utf-8",
    )

    print(f"Generated {OUTPUT_FILE} with {len(proxies)} Shadowsocks nodes.")

    if skipped:
        print(f"Skipped {len(skipped)} unsupported/invalid entries.")
        for index, reason in skipped[:20]:
            print(f"  line {index}: {reason}")


if __name__ == "__main__":
    main()
