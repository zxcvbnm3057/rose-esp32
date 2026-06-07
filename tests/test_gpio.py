"""
GPIO functionality tests for IoT Agent Bridge.

Tests GPIO configuration, input/output operations, ADC sampling, and interrupts.
Supports GPIO pin multiplexing for minimal hardware connections.
"""

import pytest
import time
import os
from typing import List, Tuple
from bridge import (
    IoTAgentClient,
    GPIO_MODE_INPUT,
    GPIO_MODE_OUTPUT,
    GPIO_MODE_INTERRUPT,
    GPIO_MODE_ADC,
    EVENT_GPIO_EDGE,
)


class TestGPIOOperations:
    """Test GPIO operations using multiplexed pins."""

    @pytest.fixture
    def client(self):
        """Client fixture - assumes ESP32 is connected with GPIO 5↔4 loopback."""
        client = IoTAgentClient()
        try:
            client.start()
            assert client.wait_for_connection(timeout=60.0)
            yield client
        finally:
            client.stop()

    def test_gpio_output(self, client):
        """Test GPIO output configuration and setting (GPIO 5)."""
        gpio_pin = 5  # Multiplexed pin for output testing

        # Configure as output
        assert client.configure_gpio(gpio_pin, GPIO_MODE_OUTPUT)

        # Set high
        assert client.set_gpio(gpio_pin, 1)

        # Set low
        assert client.set_gpio(gpio_pin, 0)

    def test_gpio_input(self, client):
        """Test GPIO input configuration and reading (GPIO 4)."""
        gpio_pin = 4  # Multiplexed pin for input testing

        # Configure as input
        assert client.configure_gpio(gpio_pin, GPIO_MODE_INPUT)

        # Read value
        value = client.get_gpio(gpio_pin)
        assert value is not None
        assert value in [0, 1]

    def test_adc_sampling(self, client):
        """Test ADC sampling on GPIO pin (GPIO 6 with potentiometer)."""
        gpio_pin = 6  # Dedicated ADC pin

        # Configure as ADC
        assert client.configure_gpio(gpio_pin, GPIO_MODE_ADC)

        # Single sample
        value = client.read_adc(gpio_pin, samples=1)
        assert value is not None
        assert 0 <= value <= 4095

        # Multiple samples
        value = client.read_adc(gpio_pin, samples=10)
        assert value is not None
        assert 0 <= value <= 4095

    def test_gpio_loopback(self, client):
        """Test GPIO loopback using multiplexed pins (GPIO 5→4)."""
        output_pin = 5  # TX pin in multiplexed pair
        input_pin = 4  # RX pin in multiplexed pair

        # Configure pins
        assert client.configure_gpio(output_pin, GPIO_MODE_OUTPUT)
        assert client.configure_gpio(input_pin, GPIO_MODE_INPUT)

        # Test loopback
        test_values = [0, 1, 0, 1, 0]

        for expected in test_values:
            assert client.set_gpio(output_pin, expected)
            time.sleep(0.01)  # Allow signal to settle
            actual = client.get_gpio(input_pin)
            assert actual == expected, f"Expected {expected}, got {actual}"

    def test_multiple_gpio_config(self, client):
        """Test configuring multiple GPIO pins (using available pins)."""
        # Use available pins that don't conflict with multiplexed pair
        pins = [2, 3]  # Avoid GPIO 4,5,6 which are used for multiplexing

        for pin in pins:
            assert client.configure_gpio(pin, GPIO_MODE_OUTPUT)
            assert client.set_gpio(pin, 0)

        # Set alternating pattern
        for i, pin in enumerate(pins):
            assert client.set_gpio(pin, i % 2)


class TestGPIOInterruptOperations:
    """Test GPIO interrupt edge capture using loopback pins."""

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

    def _drain_edge_events(self, client) -> None:
        while client.events.wait_for_event(EVENT_GPIO_EDGE, timeout=0.05) is not None:
            pass

    def test_gpio_interrupt_edge_loopback(self, client):
        """Test interrupt edge event using GPIO 5 output -> GPIO 4 interrupt input."""
        output_pin = 5
        interrupt_pin = 4

        assert client.configure_gpio(output_pin, GPIO_MODE_OUTPUT)
        assert client.configure_gpio(interrupt_pin, GPIO_MODE_INTERRUPT, edge=1)

        self._drain_edge_events(client)

        assert client.set_gpio(output_pin, 0)
        time.sleep(0.01)
        assert client.set_gpio(output_pin, 1)

        edge_evt = client.events.wait_for_event(EVENT_GPIO_EDGE, timeout=1.0)
        assert edge_evt is not None, "No GPIO edge event captured from loopback"
        assert edge_evt.gpio == interrupt_pin
        assert edge_evt.edge_type in (1, 2, 3)
