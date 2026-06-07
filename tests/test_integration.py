"""
Integration tests for IoT Agent Bridge.

Tests complete workflows combining multiple components.
"""

import pytest
import time
import threading
from typing import List, Tuple
from bridge import IoTAgentClient, EVENT_PORT_STATUS, RESOURCE_GPIO, EventCmdAck, EventError, IOT_ERR_RESOURCE_CONFLICT


class TestSystemIntegration:
    """Test system-wide integration."""

    @pytest.fixture
    def client(self):
        """Client fixture."""
        client: IoTAgentClient = IoTAgentClient()
        client.start()
        assert client.wait_for_connection(timeout=60.0)
        yield client
        client.stop()

    def test_full_gpio_workflow(self, client):
        """Test complete GPIO workflow."""
        gpio_pin = 5

        # Configure
        assert client.configure_gpio(gpio_pin, 1)  # OUTPUT

        # Set and verify
        assert client.set_gpio(gpio_pin, 1)
        time.sleep(0.01)

        # Reconfigure as input
        assert client.configure_gpio(gpio_pin, 0)  # INPUT
        value = client.get_gpio(gpio_pin)
        assert value is not None

    def test_port_management_workflow(self, client):
        """Test port bind/status across protocol mode transitions and unbind."""
        gpio_id = 5

        def _get_status():
            status_cmd = client.commands.port_status(RESOURCE_GPIO, gpio_id)
            assert status_cmd is not None
            status_evt = client.events.wait_for_event(EVENT_PORT_STATUS, timeout=1.5)
            assert status_evt is not None
            assert status_evt.resource_type == RESOURCE_GPIO
            assert status_evt.id == gpio_id
            return status_evt

        # Bind port
        bind_cmd = client.commands.port_bind(RESOURCE_GPIO, gpio_id, 1)
        assert bind_cmd is not None
        bind_ack = client.events.wait_for_response(bind_cmd, timeout=1.0)
        assert bind_ack is not None
        assert isinstance(bind_ack, EventCmdAck)
        assert bind_ack.status == 0, f"port_bind failed with error_code={bind_ack.error_code}"

        # Status after bind
        status_evt = _get_status()
        assert status_evt.in_use == 1
        assert status_evt.owner == 1

        # Switch to GPIO output protocol and verify status
        assert client.configure_gpio(gpio_id, 1)
        assert client.set_gpio(gpio_id, 1)
        status_evt = _get_status()
        assert status_evt.in_use == 1
        assert status_evt.mode == 1
        assert status_evt.value == 1

        # Switch to SIGNAL protocol on the same IO and verify mode update
        assert client.configure_gpio(gpio_id, 4)
        status_evt = _get_status()
        assert status_evt.in_use == 1
        assert status_evt.mode == 4

        # Unbind port
        unbind_cmd = client.commands.port_unbind(RESOURCE_GPIO, gpio_id)
        assert unbind_cmd is not None
        unbind_ack = client.events.wait_for_response(unbind_cmd, timeout=1.0)
        assert unbind_ack is not None
        assert isinstance(unbind_ack, EventCmdAck)
        assert unbind_ack.status == 0, f"port_unbind failed with error_code={unbind_ack.error_code}"

        # Status after unbind
        status_evt = _get_status()
        assert status_evt.in_use == 0
        assert status_evt.owner == 0

    def test_signal_communication_workflow(self, client):
        """Test signal communication workflow (GPIO 5↔4 loopback)."""
        tx_pin = 5  # Multiplexed TX pin
        rx_pin = 4  # Multiplexed RX pin

        # Configure pins for signal mode
        assert client.configure_gpio(tx_pin, 4)  # SIGNAL
        assert client.configure_gpio(rx_pin, 4)  # SIGNAL

        # Use longer pulses for better stability on ISR-based capture.
        test_signal = [(1, 3000), (0, 2000), (1, 4000), (0, 2500)]

        rx_result = {"signal": None}

        def _rx_worker():
            rx_result["signal"] = client.receive_signal(
                rx_pin,
                timeout_us=1500000,
                max_edges=32,
            )

        rx_thread = threading.Thread(target=_rx_worker, daemon=True)
        rx_thread.start()

        # Leave enough time for device side to arm ISR capture.
        time.sleep(0.15)
        assert client.send_signal(tx_pin, test_signal)

        rx_thread.join(timeout=3.0)
        assert not rx_thread.is_alive(), "RX worker did not finish"
        received = rx_result["signal"]

        assert received is not None, "No signal captured from loopback; check GPIO 5↔4 wiring"
        assert isinstance(received, list)
        assert len(received) > 0, "Signal capture completed but edge_count=0"

        # At least verify the first edge level from loopback waveform.
        assert received[0][0] in (0, 1)

    def test_uart_loopback_workflow(self, client):
        """Test UART1 self-loopback communication on GPIO 1↔3."""
        uart_id = 1
        tx_gpio = 1  # UART1 TX mapped to GPIO1
        rx_gpio = 3  # UART1 RX mapped to GPIO3

        # Configure UART and get event-driven RX listener
        listener = client.configure_uart(uart_id, baudrate=115200, tx_gpio=tx_gpio, rx_gpio=rx_gpio)
        assert listener is not None

        # Test data
        test_data = b"Hello UART Loopback Test!"

        # Send data
        assert client.send_uart(uart_id, test_data)

        # Read response (should receive the same data due to loopback)
        received = None
        stream = b""
        for _ in range(12):
            received = listener.read(timeout=0.4)
            if received:
                stream += received
                if len(stream) >= len(test_data):
                    break
                time.sleep(0.1)

        assert stream, "No UART loopback data received; check GPIO 1↔3 wiring"
        assert test_data == stream[:len(test_data)], f"UART stream did not contain payload {test_data}, got {stream}"

    def test_concurrent_operations(self, client):
        """Test concurrent GPIO operations (using non-multiplexed pins)."""
        # Use pins that don't conflict with multiplexed pair (4,5) or ADC (6)
        pins = [2, 3]  # Available GPIO pins

        # Configure all as outputs
        for pin in pins:
            assert client.configure_gpio(pin, 1)  # OUTPUT

        # Set different values
        for i, pin in enumerate(pins):
            assert client.set_gpio(pin, i % 2)

        # Read back (reconfigure as inputs)
        for pin in pins:
            assert client.configure_gpio(pin, 0)  # INPUT
            value = client.get_gpio(pin)
            assert value is not None


class TestPerformance:
    """Test performance characteristics."""

    @pytest.fixture
    def client(self):
        """Client fixture."""
        client = IoTAgentClient()
        try:
            client.start()
            assert client.wait_for_connection(timeout=60.0)
            yield client
        finally:
            client.stop()

    def test_command_throughput(self, client):
        """Test command throughput."""
        gpio_pin = 5

        assert client.configure_gpio(gpio_pin, 1)  # OUTPUT

        # Measure time for multiple set operations
        start_time = time.time()
        num_operations = 100

        for i in range(num_operations):
            client.set_gpio(gpio_pin, i % 2)

        end_time = time.time()
        ops_per_sec = num_operations / (end_time - start_time)

        print(f"GPIO set throughput: {ops_per_sec:.1f} ops/sec")
        assert ops_per_sec > 10  # At least 10 ops/sec

    def test_signal_processing_performance(self, client):
        """Test signal processing performance."""
        gpio_pin = 5

        assert client.configure_gpio(gpio_pin, 4)  # SIGNAL

        # Large signal
        large_signal = [(i % 2, 10) for i in range(1000)]  # 1000 edges, 10us each

        start_time = time.time()
        result = client.send_signal(gpio_pin, large_signal)
        end_time = time.time()

        assert result is True
        duration = end_time - start_time
        print(f"Large signal transmission: {duration:.3f} seconds")
        # Should complete in reasonable time


class TestErrorHandling:
    """Test error handling and edge cases."""

    @pytest.fixture
    def client(self):
        """Client fixture."""
        client = IoTAgentClient()
        try:
            client.start()
            assert client.wait_for_connection(timeout=60.0)
            yield client
        finally:
            client.stop()

    def test_invalid_gpio_operations(self, client):
        """Test operations on invalid GPIO pins."""
        # GPIO 31 may be invalid
        result = client.configure_gpio(31, 1)
        assert result is False, "Configuring an invalid GPIO should fail"

    def test_timeout_handling(self, client):
        """Test timeout handling."""
        gpio_pin = 4

        assert client.configure_gpio(gpio_pin, 4)  # SIGNAL

        # Receive with very short timeout and no transmitted signal.
        received = client.receive_signal(gpio_pin, timeout_us=1000, max_edges=10)

        # Should time out without capturing a signal.
        assert received is None, "receive_signal should return None on timeout when no signal is transmitted"

    def test_resource_conflicts(self, client):
        """Test resource conflict handling."""
        gpio_pin = 5

        bind_cmd = client.commands.port_bind(RESOURCE_GPIO, gpio_pin, 1)
        assert bind_cmd is not None
        bind_ack = client.events.wait_for_response(bind_cmd, timeout=1.0)
        assert bind_ack is not None
        assert isinstance(bind_ack, EventCmdAck)
        assert bind_ack.status == 0, f"port_bind failed with error_code={bind_ack.error_code}"

        conflict_cmd = client.commands.port_bind(RESOURCE_GPIO, gpio_pin, 2)
        assert conflict_cmd is not None
        conflict_result = client.events.wait_for_response(conflict_cmd, timeout=1.0)
        assert conflict_result is not None
        assert isinstance(conflict_result, EventError)
        assert conflict_result.err_code == IOT_ERR_RESOURCE_CONFLICT

        unbind_cmd = client.commands.port_unbind(RESOURCE_GPIO, gpio_pin)
        assert unbind_cmd is not None
        unbind_ack = client.events.wait_for_response(unbind_cmd, timeout=1.0)
        assert unbind_ack is not None
        assert isinstance(unbind_ack, EventCmdAck)
        assert unbind_ack.status == 0, f"port_unbind failed with error_code={unbind_ack.error_code}"
