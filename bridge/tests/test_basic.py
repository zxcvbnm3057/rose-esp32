"""
Basic functionality tests for IoT Agent Bridge.

These tests run against a real ESP32 device connected to the bridge server.
"""

import pytest

from ..src import IoTAgentClient, GPIO_MODE_OUTPUT, GPIO_MODE_INPUT


class TestBasicFunctionality:
    """Test basic client functionality against real hardware."""

    @pytest.fixture
    def client(self):
        """Client fixture for real ESP32 connection."""
        client = IoTAgentClient('0.0.0.0', 8080)
        try:
            client.start()
            assert client.wait_for_connection(timeout=60.0)
            yield client
        finally:
            client.stop()

    def test_connection(self, client):
        """Test client connection state."""
        assert client.is_connected()

    def test_ping(self, client):
        """Test ping command."""
        assert client.ping() is True

    def test_heartbeat(self, client):
        """Test heartbeat command."""
        state = client.heartbeat()
        assert state in (0, 1)

    def test_gpio_config(self, client):
        """Test GPIO configuration command."""
        assert client.configure_gpio(5, GPIO_MODE_OUTPUT) is True

    def test_gpio_set_get(self, client):
        """Test GPIO set then read-back via GPIO 5→4 loopback."""
        # GPIO 5 is MTDI strapping pin on ESP32-C6; set/get may be unreliable on
        # OUTPUT. Use GPIO 5 OUTPUT → GPIO 4 INPUT loopback instead.
        assert client.configure_gpio(5, GPIO_MODE_OUTPUT)
        assert client.configure_gpio(4, GPIO_MODE_INPUT)
        assert client.set_gpio(5, 1)
        value = client.get_gpio(4)
        assert value == 1, f"Loopback failed: set GPIO5=1, read GPIO4={value}"
        assert client.set_gpio(5, 0)
        value = client.get_gpio(4)
        assert value == 0, f"Loopback failed: set GPIO5=0, read GPIO4={value}"
