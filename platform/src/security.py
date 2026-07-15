"""Source network allowlists for the platform, console, and device bridge."""
from __future__ import annotations

import ipaddress
import os
from functools import lru_cache


def _parse_networks(value: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    networks = []
    for item in value.split(","):
        item = item.strip()
        if item:
            networks.append(ipaddress.ip_network(item, strict=False))
    return tuple(networks)


@lru_cache
def networks_for(name: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    defaults = {
        "ROSE_API_ALLOWLIST": "127.0.0.1/32,::1/128",
        "ROSE_CONSOLE_ALLOWLIST": "127.0.0.1/32,::1/128",
        "ROSE_DEVICE_ALLOWLIST": "127.0.0.1/32,::1/128",
    }
    return _parse_networks(os.environ.get(name, defaults[name]))


def is_allowed(address: str | None, allowlist_name: str) -> bool:
    if not address:
        return False
    try:
        client_ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(
        client_ip.version == network.version and client_ip in network
        for network in networks_for(allowlist_name)
    )