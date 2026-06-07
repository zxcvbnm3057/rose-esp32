"""
GPIO interrupt / edge event tests for IoT Agent Bridge.

Validates EVENT_GPIO_EDGE reporting when GPIO is configured in INTERRUPT mode.
Uses GPIO 5→4 loopback: driving GPIO 5 OUTPUT toggles triggers edge ISR on GPIO 4.
"""

import time

import pytest

from bridge import (
    IoTAgentClient,
    GPIO_MODE_INTERRUPT,
    GPIO_MODE_OUTPUT,
    GPIO_MODE_INPUT,
    EVENT_GPIO_EDGE,
    RESOURCE_GPIO,
)


class TestGpioEdgeEvent:
    """Test GPIO edge event generation and parsing."""

    TX_PIN = 5
    RX_PIN = 4

    @pytest.fixture
    def client(self):
        client = IoTAgentClient()
        try:
            client.start()
            assert client.wait_for_connection(timeout=60.0)
            yield client
        finally:
            client.stop()

    def test_gpio_interrupt_mode_generates_edge_events(self, client):
        """Configure RX pin as INTERRUPT and verify edge events on TX toggling."""
        # Configure TX as OUTPUT, RX as INTERRUPT (any edge)
        assert client.configure_gpio(self.TX_PIN, GPIO_MODE_OUTPUT)
        assert client.configure_gpio(self.RX_PIN, GPIO_MODE_INTERRUPT, edge=3)  # ANYEDGE

        # Clear stale events from configuration
        client.events.clear_pending()
        time.sleep(0.05)

        # Toggle TX pin several times to generate edges on loopback
        for level in (1, 0, 1, 0, 1):
            assert client.set_gpio(self.TX_PIN, level)
            time.sleep(0.01)

        # Wait a moment for ISR to fire and events to arrive
        time.sleep(0.3)

        # Collect edge events
        edges = []
        for _ in range(10):
            evt = client.events.wait_for_event(EVENT_GPIO_EDGE, timeout=0.5)
            if evt is None:
                break
            edges.append(evt)

        # We should see at least some edge events on the RX pin
        rx_edges = [e for e in edges if hasattr(e, 'gpio') and e.gpio == self.RX_PIN]
        assert len(rx_edges) > 0, (
            f"No edge events captured on GPIO {self.RX_PIN}. "
            "Check GPIO 5→4 loopback wiring."
        )

        # Each edge event should have valid fields
        for e in rx_edges:
            assert hasattr(e, 'edge_type')
            assert hasattr(e, 'timestamp_us')
            assert e.edge_type in (0, 1, 2), f"Unexpected edge_type: {e.edge_type}"
            assert e.timestamp_us > 0

    def test_gpio_interrupt_edge_count_matches_toggles(self, client):
        """Toggle TX N times, verify RX gets roughly 2N edge events (rise+fall)."""
        assert client.configure_gpio(self.TX_PIN, GPIO_MODE_OUTPUT)
        assert client.configure_gpio(self.RX_PIN, GPIO_MODE_INTERRUPT, edge=3)

        client.events.clear_pending()
        time.sleep(0.05)

        TOGGLES = 5  # 5 full cycles = 10 edges
        for _ in range(TOGGLES):
            client.set_gpio(self.TX_PIN, 1)
            time.sleep(0.005)
            client.set_gpio(self.TX_PIN, 0)
            time.sleep(0.005)

        time.sleep(0.3)

        edges = []
        for _ in range(30):
            evt = client.events.wait_for_event(EVENT_GPIO_EDGE, timeout=0.3)
            if evt is None:
                break
            if hasattr(evt, 'gpio') and evt.gpio == self.RX_PIN:
                edges.append(evt)

        # Allow some jitter: expect at least TOGGLES edges (conservative)
        assert len(edges) >= TOGGLES, (
            f"Expected >= {TOGGLES} edges on GPIO {self.RX_PIN}, got {len(edges)}"
        )

    def test_input_mode_does_not_generate_edge_events(self, client):
        """INPUT mode (not INTERRUPT) should not trigger edge events on toggling."""
        assert client.configure_gpio(self.TX_PIN, GPIO_MODE_OUTPUT)
        assert client.configure_gpio(self.RX_PIN, GPIO_MODE_INPUT)

        client.events.clear_pending()
        time.sleep(0.05)

        for _ in range(3):
            client.set_gpio(self.TX_PIN, 1)
            time.sleep(0.01)
            client.set_gpio(self.TX_PIN, 0)
            time.sleep(0.01)

        time.sleep(0.3)

        evt = client.events.wait_for_event(EVENT_GPIO_EDGE, timeout=0.5)
        # In INPUT mode, ISR is not installed so no edge events expected
        assert evt is None, f"Unexpected edge event in INPUT mode: {evt}"
