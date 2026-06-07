"""Global pytest fixtures for hardware resource cleanup between tests."""

import time

import pytest

from bridge import IoTAgentClient, RESOURCE_GPIO, RESOURCE_UART


def _unbind_all(client, deadline: float):
    """Unbind GPIO/UART ports quickly; stop early if deadline is reached."""
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


@pytest.fixture
def client():
    """Client fixture for real ESP32 connection."""
    client = IoTAgentClient()
    try:
        client.start()
        assert client.wait_for_connection(timeout=60.0)
        yield client
    finally:
        client.stop()


@pytest.fixture(autouse=True)
def cleanup_resources_before_and_after_test(client):
    """Reset port bindings before and after each test.

    The firmware keeps resource ownership across disconnects by design,
    so explicit cleanup is required to avoid cross-test interference.
    """
    deadline = time.monotonic() + 5.0  # Hard cap per cleanup phase
    _unbind_all(client, deadline)
    client.events.clear_pending()

    yield

    if client.is_connected():
        deadline = time.monotonic() + 5.0
        _unbind_all(client, deadline)
