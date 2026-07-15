"""Source allowlist tests."""
from src.security import _parse_networks, is_allowed, networks_for


def test_parse_networks_supports_ipv4_and_ipv6():
    networks = _parse_networks("192.168.137.200/32, ::1/128")
    assert str(networks[0]) == "192.168.137.200/32"
    assert str(networks[1]) == "::1/128"


def test_api_allowlist_accepts_ha_and_bastion(monkeypatch):
    monkeypatch.setenv("ROSE_API_ALLOWLIST", "192.168.137.200/32,172.18.0.254/32")
    networks_for.cache_clear()
    assert is_allowed("192.168.137.200", "ROSE_API_ALLOWLIST")
    assert is_allowed("172.18.0.254", "ROSE_API_ALLOWLIST")
    assert not is_allowed("192.168.137.201", "ROSE_API_ALLOWLIST")


def test_device_allowlist_can_be_narrowed(monkeypatch):
    monkeypatch.setenv("ROSE_DEVICE_ALLOWLIST", "192.168.137.51/32")
    networks_for.cache_clear()
    assert is_allowed("192.168.137.51", "ROSE_DEVICE_ALLOWLIST")
    assert not is_allowed("192.168.137.52", "ROSE_DEVICE_ALLOWLIST")
    assert not is_allowed("not-an-ip", "ROSE_DEVICE_ALLOWLIST")
