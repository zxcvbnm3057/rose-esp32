"""
Port binding / status / unbinding tests for IoT Agent Bridge.

Validates CMD_PORT_BIND, CMD_PORT_UNBIND, CMD_PORT_STATUS and the
resulting EVENT_PORT_STATUS with strict field assertions.
"""

import pytest

from ..src import (
    IoTAgentClient,
    GPIO_MODE_INPUT,
    EVENT_PORT_STATUS,
    RESOURCE_GPIO,
    RESOURCE_UART,
    EVENT_ERROR,
)


class TestPortLifecycle:
    """Test full port bind → status → unbind lifecycle."""

    GPIO_ID = 5
    UART_ID = 1

    @pytest.fixture
    def client(self):
        client = IoTAgentClient()
        try:
            client.start()
            assert client.wait_for_connection(timeout=60.0)
            yield client
        finally:
            client.stop()

    # ── GPIO ──────────────────────────────────────────────────────

    def test_gpio_bind_unbind_cycle(self, client):
        """Bind GPIO, verify in_use, then unbind and verify released."""
        gpio = self.GPIO_ID

        # Bind
        cmd_id = client.commands.port_bind(RESOURCE_GPIO, gpio, owner_id=0x1234)
        assert cmd_id is not None
        ack = client.events.wait_for_response(cmd_id, timeout=2.0)
        assert ack is not None and ack.status == 0, f"Bind failed: {ack}"

        # Check status
        status = self._get_port_status(client, RESOURCE_GPIO, gpio)
        assert status is not None, "No PORT_STATUS event received"
        assert status.resource_type == RESOURCE_GPIO
        assert status.id == gpio
        assert status.in_use == 1, f"Expected in_use=1, got {status.in_use}"

        # Unbind
        cmd_id = client.commands.port_unbind(RESOURCE_GPIO, gpio)
        assert cmd_id is not None
        ack = client.events.wait_for_response(cmd_id, timeout=2.0)
        assert ack is not None and ack.status == 0, f"Unbind failed: {ack}"

        # Verify released
        status = self._get_port_status(client, RESOURCE_GPIO, gpio)
        assert status is not None
        assert status.in_use == 0, f"Expected in_use=0 after unbind, got {status.in_use}"

    def test_gpio_port_status_strict_fields(self, client):
        """Query port status and assert all fields are present and typed correctly."""
        gpio = self.GPIO_ID

        # First configure as INPUT to set a known mode
        assert client.configure_gpio(gpio, GPIO_MODE_INPUT)

        status = self._get_port_status(client, RESOURCE_GPIO, gpio)
        assert status is not None

        assert isinstance(status.resource_type, int)
        assert isinstance(status.id, int)
        assert isinstance(status.mode, int)
        assert isinstance(status.owner, int)
        assert isinstance(status.in_use, int)
        assert isinstance(status.value, int)

        assert status.resource_type == RESOURCE_GPIO
        assert status.id == gpio
        assert status.in_use == 1
        # mode might be 0 (INPUT) after configure_gpio sets it
        assert status.mode in (0, GPIO_MODE_INPUT), f"Unexpected mode: {status.mode}"

    def test_double_bind_rejected(self, client):
        """Binding an already-bound port should fail (resource conflict)."""
        gpio = self.GPIO_ID

        cmd_id = client.commands.port_bind(RESOURCE_GPIO, gpio, owner_id=1)
        assert cmd_id is not None
        ack = client.events.wait_for_response(cmd_id, timeout=2.0)
        assert ack is not None and ack.status == 0

        # Second bind should be rejected
        cmd_id2 = client.commands.port_bind(RESOURCE_GPIO, gpio, owner_id=2)
        assert cmd_id2 is not None
        ack2 = client.events.wait_for_response(cmd_id2, timeout=2.0)
        # Firmware sends EVENT_ERROR for double bind; EventError has no .status
        is_error = ack2 is not None and hasattr(ack2, 'err_code')
        is_fail_ack = ack2 is not None and hasattr(ack2, 'status') and ack2.status != 0
        assert ack2 is None or is_error or is_fail_ack, (
            f"Double bind should fail, got {type(ack2).__name__ if ack2 else 'None'}")

        # Cleanup
        client.commands.port_unbind(RESOURCE_GPIO, gpio)

    def test_unbind_nonexistent_port(self, client):
        """Unbinding a non-bound port should fail gracefully."""
        gpio = 27  # unlikely to be bound

        cmd_id = client.commands.port_unbind(RESOURCE_GPIO, gpio)
        assert cmd_id is not None

        # Either timeout (None), EVENT_ERROR, or failure ACK — all acceptable
        response = client.events.wait_for_response(cmd_id, timeout=2.0)
        if response is not None:
            is_error = hasattr(response, 'err_code')
            is_fail = hasattr(response, 'status') and response.status != 0
            assert is_error or is_fail, (f"Unbind of unbound port should not succeed: {type(response).__name__}")

    # ── UART ──────────────────────────────────────────────────────

    def test_uart_port_status_fields(self, client):
        """Query UART port status; validate field types and defaults for unconfigured port."""
        uart_id = self.UART_ID

        status = self._get_port_status(client, RESOURCE_UART, uart_id)
        assert status is not None

        assert status.resource_type == RESOURCE_UART
        assert status.id == uart_id
        # Unconfigured UART should report in_use=0
        assert status.in_use == 0, f"Expected unconfigured UART in_use=0, got {status.in_use}"

    # ── helpers ───────────────────────────────────────────────────

    @staticmethod
    def _get_port_status(client, resource_type: int, port_id: int):
        cmd_id = client.commands.port_status(resource_type, port_id)
        if cmd_id is None:
            return None
        return client.events.wait_for_event(EVENT_PORT_STATUS, timeout=2.0)
