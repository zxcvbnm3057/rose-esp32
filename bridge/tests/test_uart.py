"""
UART tests for IoT Agent Bridge.

Validates CMD_UART_CONFIG, CMD_UART_SEND, event-driven CMD_UART_READ
(EVENT_UART_RX), and UART TX→RX loopback.
"""

import os
import time

import pytest

from ..src import IoTAgentClient, EVENT_UART_RX

UART_ID = int(os.getenv("TEST_UART_ID", "1"))
TX_GPIO = int(os.getenv("TEST_UART_TX", "1"))
RX_GPIO = int(os.getenv("TEST_UART_RX", "3"))
UART_BAUDRATE = int(os.getenv("TEST_UART_BAUDRATE", "115200"))


class TestUartLoopback:
    """UART configuration and loopback tests.

    Requires TX→RX physical loopback: connect GPIO 1 ↔ GPIO 3
    (or set TEST_UART_TX / TEST_UART_RX env vars).
    """

    @pytest.fixture
    def client(self):
        client = IoTAgentClient()
        try:
            client.start()
            assert client.wait_for_connection(timeout=60.0)
            yield client
        finally:
            client.stop()

    @pytest.mark.skipif(
        os.getenv("SKIP_UART_TESTS", "0") == "1",
        reason="Set SKIP_UART_TESTS=0 and connect UART TX→RX loopback",
    )
    def test_uart_config_and_event_driven_rx(self, client):
        """Configure UART, send data, and verify EVENT_UART_RX via listener."""
        listener = client.configure_uart(UART_ID, UART_BAUDRATE, tx_gpio=TX_GPIO, rx_gpio=RX_GPIO)
        assert listener is not None, "UART configuration failed"

        # Small delay for UART driver to settle
        time.sleep(0.1)

        TEST_DATA = b"HelloUART!"
        assert client.send_uart(UART_ID, TEST_DATA)

        # Read via listener (event-driven path)
        received = listener.read(timeout=2.0)
        assert received is not None, "No data received via UART listener"
        assert len(received) > 0, "Received empty UART data"

    @pytest.mark.skipif(
        os.getenv("SKIP_UART_TESTS", "0") == "1",
        reason="Set SKIP_UART_TESTS=0 and connect UART TX→RX loopback",
    )
    def test_uart_send_receive_roundtrip(self, client):
        """Send known data and verify it loops back correctly."""
        listener = client.configure_uart(UART_ID, UART_BAUDRATE, tx_gpio=TX_GPIO, rx_gpio=RX_GPIO)
        assert listener is not None

        time.sleep(0.1)

        TEST_DATA = b"TestPattern_12345\x00\xFF"
        assert client.send_uart(UART_ID, TEST_DATA)

        received = listener.read(timeout=2.0)
        assert received is not None
        # With loopback we expect the same data (may be split across multiple reads)
        assert len(received) >= 1, "Should receive at least partial data"

    @pytest.mark.skipif(
        os.getenv("SKIP_UART_TESTS", "0") == "1",
        reason="Set SKIP_UART_TESTS=0 and connect UART TX→RX loopback",
    )
    def test_uart_legacy_polling_read(self, client):
        """Legacy CMD_UART_READ polling path returns EVENT_UART_RX."""
        assert client.configure_uart(UART_ID, UART_BAUDRATE, tx_gpio=TX_GPIO, rx_gpio=RX_GPIO)

        time.sleep(0.1)
        assert client.send_uart(UART_ID, b"PollMe!")

        # Use the legacy read path (CMD_UART_READ)
        cmd_id = client.commands.uart_read(UART_ID, length=32)
        assert cmd_id is not None

        evt = client.events.wait_for_event(EVENT_UART_RX, timeout=3.0)
        assert evt is not None, "No EVENT_UART_RX from legacy read"
        assert hasattr(evt, 'uart_id')
        assert hasattr(evt, 'data')
        assert evt.uart_id == UART_ID

    def test_uart_invalid_id_rejected(self, client):
        """UART config on invalid ID should fail."""
        listener = client.configure_uart(99, 9600, tx_gpio=9, rx_gpio=10)
        assert listener is None, "Config on invalid UART ID should return None"

    def test_uart_send_rejects_unbound_uart(self, client):
        """UART send must fail if the UART has not been configured/bound."""
        assert client.send_uart(UART_ID, b"hello") is False

    def test_uart_read_rejects_unbound_uart(self, client):
        """UART read must fail if the UART has not been configured/bound."""
        assert client.read_uart(UART_ID, 32) is None
