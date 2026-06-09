"""pytest fixtures for bridge tests.

Hardware tests (real ESP32): set env USE_REAL_DEVICE=1
Unit tests (protocol/events): run without env var.
"""

import time
import os
import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "hardware: test requires real ESP32")


def pytest_collection_modifyitems(config, items):
    if os.environ.get("USE_REAL_DEVICE") != "1":
        skip_hw = pytest.mark.skip(reason="USE_REAL_DEVICE not set")
        for item in items:
            if "hardware" in item.keywords:
                item.add_marker(skip_hw)


@pytest.fixture
def client():
    """Client fixture requiring real ESP32."""
    from ..src import IoTAgentClient
    client = IoTAgentClient()
    try:
        client.start()
        assert client.wait_for_connection(timeout=60.0)
        yield client
    finally:
        client.stop()


def _unbind_all(client, deadline: float):
    from ..src import RESOURCE_GPIO, RESOURCE_UART
    for gpio in range(31):
        if time.monotonic() > deadline:
            return
        cmd_id = client.commands.port_unbind(RESOURCE_GPIO, gpio)
        if cmd_id is not None:
            client.events.wait_for_response(cmd_id, timeout=0.05)
    for uart_id in range(2):
        if time.monotonic() > deadline:
            return
        cmd_id = client.commands.port_unbind(RESOURCE_UART, uart_id)
        if cmd_id is not None:
            client.events.wait_for_response(cmd_id, timeout=0.05)


@pytest.fixture(autouse=True)
def cleanup_resources_before_and_after_test(client):
    deadline = time.monotonic() + 5.0
    _unbind_all(client, deadline)
    client.events.clear_pending()
    yield
    if client.is_connected():
        deadline = time.monotonic() + 5.0
        _unbind_all(client, deadline)
