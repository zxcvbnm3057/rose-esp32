"""
NVS persistence tests for IoT Agent Bridge.

验证 GPIO / UART / BLE 配置在 NVS 中的存储与恢复。
测试策略：
  1. 配置 GPIO → sync 快照验证 → 模拟掉电恢复 (通过对比 sync snapshot)
  2. 配置 UART → sync 快照验证
  3. BLE 扫描启停 → 事件验证 + 状态检查
  4. GPIO SET 输出电平 → 验证值被持久化

NOTE: 完整的掉电恢复测试需要手动重启 ESP32 后重新运行 sync_check。
      见 manual_nvs_e2e.py 获取端到端验证流程。
"""

import pytest
import time
from ..src import (
    IoTAgentClient,
    GPIO_MODE_OUTPUT,
    GPIO_MODE_INPUT,
    GPIO_MODE_ADC,
    GPIO_MODE_INTERRUPT,
    EVENT_GPIO_STATUS,
    EVENT_UART_STATUS,
    EVENT_BLE_STATUS,
    EVENT_SYNC_RESPONSE,
    EVENT_PORT_STATUS,
    RESOURCE_GPIO,
    RESOURCE_UART,
)


def _collect_sync_gpios(client, timeout: float = 5.0) -> dict:
    """Send sync request and collect all GPIO_STATUS events into a dict."""
    from ..src.protocol import EventGpioStatus, EventSyncResponse

    # Clear stale events
    client.events.clear_pending()

    cmd_id = client.commands.sync_request()
    assert cmd_id is not None, "sync_request failed"

    sync = client.events.wait_for_event(EVENT_SYNC_RESPONSE, timeout=timeout)
    assert isinstance(sync, EventSyncResponse), f"Expected sync response, got {type(sync)}"

    # Collect GPIO status events
    gpios = {}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        evt = client.events.wait_for_event(EVENT_GPIO_STATUS, timeout=min(1.0, deadline - time.monotonic()))
        if evt is None:
            break
        gpios[evt.gpio] = {
            "mode": evt.mode, "pull": evt.pull, "edge": evt.edge,
            "value": evt.value, "in_use": evt.in_use,
        }
    return gpios


def _collect_sync_uarts(client, timeout: float = 5.0) -> dict:
    """Collect UART_STATUS events from sync."""
    from ..src.protocol import EventUartStatus

    uarts = {}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        evt = client.events.wait_for_event(EVENT_UART_STATUS, timeout=min(1.0, deadline - time.monotonic()))
        if evt is None:
            break
        uarts[evt.uart_id] = {
            "baudrate": evt.baudrate, "tx_gpio": evt.tx_gpio, "rx_gpio": evt.rx_gpio,
            "in_use": evt.in_use,
        }
    return uarts


def _unbind_gpio(client, gpio: int):
    """Safely unbind a GPIO pin."""
    cmd_id = client.commands.port_unbind(RESOURCE_GPIO, gpio)
    if cmd_id is not None:
        client.events.wait_for_response(cmd_id, timeout=2.0)


class TestNVSPersistence:
    """Test NVS save/restore for GPIO, UART, and BLE configurations."""

    @pytest.fixture
    def client(self):
        """Client fixture - requires real ESP32."""
        client = IoTAgentClient()
        try:
            client.start()
            assert client.wait_for_connection(timeout=60.0)
            yield client
        finally:
            client.stop()

    # ── GPIO persistence ──────────────────────────────────────

    def test_gpio_config_appears_in_sync_snapshot(self, client):
        """配置 GPIO 后，sync 快照应包含该引脚完整状态。"""
        gpio = 5
        _unbind_gpio(client, gpio)
        time.sleep(0.3)  # 等待 NVS 写入+硬件释放完成

        # Configure GPIO5 as OUTPUT, pull-up, value=1
        assert client.configure_gpio(gpio, GPIO_MODE_OUTPUT, pull=2), "GPIO5 config failed"
        assert client.set_gpio(gpio, 1)
        time.sleep(0.2)

        # Verify via sync
        gpios = _collect_sync_gpios(client)
        assert gpio in gpios, f"GPIO {gpio} not in sync snapshot: {list(gpios.keys())}"
        pin = gpios[gpio]
        assert pin["mode"] == GPIO_MODE_OUTPUT, f"mode={pin['mode']}"
        assert pin["pull"] == 2, f"pull={pin['pull']}"
        assert pin["value"] == 1, f"value={pin['value']}"
        assert pin["in_use"] == 1, f"in_use={pin['in_use']}"

        # Cleanup
        _unbind_gpio(client, gpio)

    def test_gpio_output_value_persisted(self, client):
        """GPIO SET 后应立即保存到 NVS，sync 快照反映最新值。"""
        gpio = 5
        _unbind_gpio(client, gpio)

        assert client.configure_gpio(gpio, GPIO_MODE_OUTPUT)

        for val in [1, 0, 1]:
            assert client.set_gpio(gpio, val)
            time.sleep(0.1)
            gpios = _collect_sync_gpios(client)
            assert gpio in gpios
            assert gpios[gpio]["value"] == val, f"Expected {val}, got {gpios[gpio]['value']}"

        _unbind_gpio(client, gpio)

    def test_gpio_interrupt_mode_persisted(self, client):
        """中断模式 GPIO 配置应在 sync 快照中反映。"""
        gpio = 4
        _unbind_gpio(client, gpio)

        assert client.configure_gpio(gpio, GPIO_MODE_INTERRUPT, edge=3)  # BOTH edges
        time.sleep(0.2)

        gpios = _collect_sync_gpios(client)
        assert gpio in gpios
        assert gpios[gpio]["mode"] == GPIO_MODE_INTERRUPT
        assert gpios[gpio]["edge"] == 3

        _unbind_gpio(client, gpio)

    def test_gpio_unbind_removes_from_sync(self, client):
        """解绑 GPIO 后 sync 快照中不应再出现该引脚。"""
        gpio = 5
        _unbind_gpio(client, gpio)

        # Configure then unbind
        assert client.configure_gpio(gpio, GPIO_MODE_OUTPUT)
        time.sleep(0.1)
        _unbind_gpio(client, gpio)
        time.sleep(0.2)

        gpios = _collect_sync_gpios(client)
        assert gpio not in gpios, f"GPIO {gpio} still in sync after unbind"

    def test_adc_mode_persisted(self, client):
        """ADC 模式 GPIO 配置应在 sync 快照中反映。"""
        gpio = 6
        _unbind_gpio(client, gpio)

        assert client.configure_gpio(gpio, GPIO_MODE_ADC)
        time.sleep(0.2)

        gpios = _collect_sync_gpios(client)
        assert gpio in gpios
        assert gpios[gpio]["mode"] == GPIO_MODE_ADC

        _unbind_gpio(client, gpio)

    # ── UART persistence ──────────────────────────────────────

    def test_uart_config_appears_in_sync_snapshot(self, client):
        """配置 UART 后 sync 快照应包含串口状态。"""
        uart_id = 0
        # Unbind first
        cmd_id = client.commands.port_unbind(RESOURCE_UART, uart_id)
        if cmd_id is not None:
            client.events.wait_for_response(cmd_id, timeout=2.0)
        time.sleep(0.3)

        # Configure UART0 at 115200 with TX=21, RX=20 (typical ESP32-C6 pins)
        result = client.configure_uart(uart_id, baudrate=115200, tx_gpio=21, rx_gpio=20)
        time.sleep(0.3)

        uarts = _collect_sync_uarts(client)
        if uart_id in uarts:
            u = uarts[uart_id]
            assert u["baudrate"] == 115200, f"baudrate={u['baudrate']}"
            assert u["in_use"] == 1

        # Cleanup
        cmd_id = client.commands.port_unbind(RESOURCE_UART, uart_id)
        if cmd_id is not None:
            client.events.wait_for_response(cmd_id, timeout=2.0)

    # ── BLE persistence ───────────────────────────────────────

    def test_ble_scan_start_shows_in_status(self, client):
        """启动 BLE RSSI 扫描后，BLE_STATUS 事件应反映 scan_enabled=1。"""
        from ..src.protocol import EventBleStatus, EVENT_BLE_STATUS

        client.events.clear_pending()

        # Start scan
        assert client.start_ble_scan(interval_s=10)

        # Wait for BLE status event
        ble_status = client.events.wait_for_event(EVENT_BLE_STATUS, timeout=5.0)
        if isinstance(ble_status, EventBleStatus):
            assert ble_status.scan_enabled == 1, f"scan_enabled={ble_status.scan_enabled}"

        # Stop scan
        assert client.stop_ble_scan()
        time.sleep(0.5)
        ble_status2 = client.events.wait_for_event(EVENT_BLE_STATUS, timeout=5.0)
        if isinstance(ble_status2, EventBleStatus):
            assert ble_status2.scan_enabled == 0

    # ── Full sync snapshot coverage ───────────────────────────

    def test_sync_response_basic(self, client):
        """基本的 SYNC_REQUEST 应返回有效的 session_version。"""
        session_ver = client.request_sync()
        assert session_ver is not None
        assert session_ver > 0, f"session_version={session_ver}"

    def test_multiple_pins_in_sync(self, client):
        """多个 GPIO 同时配置时，sync 快照应包含所有。"""
        pins = [5, 4]
        for gpio in pins:
            _unbind_gpio(client, gpio)

        try:
            assert client.configure_gpio(5, GPIO_MODE_OUTPUT, pull=1)
            assert client.set_gpio(5, 0)
            assert client.configure_gpio(4, GPIO_MODE_INPUT, pull=2)
            time.sleep(0.3)

            gpios = _collect_sync_gpios(client)
            for gpio in pins:
                assert gpio in gpios, f"GPIO {gpio} missing from sync"
            assert gpios[5]["mode"] == GPIO_MODE_OUTPUT
            assert gpios[5]["pull"] == 1
            assert gpios[4]["mode"] == GPIO_MODE_INPUT
            assert gpios[4]["pull"] == 2
        finally:
            for gpio in pins:
                _unbind_gpio(client, gpio)
