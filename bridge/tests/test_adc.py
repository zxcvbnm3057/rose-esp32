"""
ADC sampling tests for IoT Agent Bridge.

Validates CMD_ADC_SAMPLE and EVENT_ADC_VALUE event parsing.
Requires a voltage on GPIO 6 (potentiometer or fixed voltage source).
"""

import os

import pytest

from ..src import IoTAgentClient, EVENT_ADC_VALUE, GPIO_MODE_ADC

ADC_GPIO = int(os.getenv("TEST_ADC_GPIO", "6"))


class TestAdcSampling:
    """Test ADC sampling functionality."""

    @pytest.fixture
    def client(self):
        client = IoTAgentClient()
        try:
            client.start()
            assert client.wait_for_connection(timeout=60.0)
            yield client
        finally:
            client.stop()

    def test_adc_single_sample_returns_valid_range(self, client):
        """Configure GPIO as ADC and read a single sample."""
        gpio = ADC_GPIO

        assert client.configure_gpio(gpio, GPIO_MODE_ADC)

        value = client.read_adc(gpio, samples=1)
        assert value is not None, "No ADC value returned"
        assert isinstance(value, int)
        # ADC on ESP32 is 12-bit (0-4095)
        assert 0 <= value <= 4095, f"ADC value {value} out of range [0, 4095]"

    def test_adc_event_structure(self, client):
        """Verify EVENT_ADC_VALUE event has correct fields."""
        gpio = ADC_GPIO

        assert client.configure_gpio(gpio, GPIO_MODE_ADC)

        cmd_id = client.commands.adc_sample(gpio, samples=1)
        assert cmd_id is not None

        evt = client.events.wait_for_event(EVENT_ADC_VALUE, timeout=2.0)
        assert evt is not None, "No EVENT_ADC_VALUE received"
        assert hasattr(evt, 'gpio')
        assert hasattr(evt, 'value')
        assert hasattr(evt, 'timestamp_us')
        assert evt.gpio == gpio
        assert 0 <= evt.value <= 4095
        assert evt.timestamp_us > 0

    def test_adc_multi_sample_averaging(self, client):
        """Multiple samples should produce a reasonable averaged value."""
        gpio = ADC_GPIO

        assert client.configure_gpio(gpio, GPIO_MODE_ADC)

        value_many = client.read_adc(gpio, samples=8)
        assert value_many is not None
        assert 0 <= value_many <= 4095

    def test_adc_invalid_gpio_rejected(self, client):
        """ADC on GPIO 31 (invalid) should fail."""
        result = client.read_adc(31, samples=1)
        assert result is None, "ADC on invalid GPIO should return None"
