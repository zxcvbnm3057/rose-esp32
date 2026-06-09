# Backend API 测试

## 快速开始

```bash
cd backend

# Mock 模式（无需 ESP32，使用内存 ASGI 客户端）
.\.conda\python.exe -m pytest tests/ -v

# 真实设备模式（需先启动后端 + ESP32 已连接）
.\.conda\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 &
$env:USE_REAL_DEVICE=1
.\.conda\python.exe -m pytest tests/ -v
```

## 测试模式

| 模式 | 环境变量 | 桥接 | 适合 |
|------|---------|------|------|
| **Mock** | 默认 | 全部 mock | CI、快速验证逻辑 |
| **Real** | `USE_REAL_DEVICE=1` | 真实 ESP32 TCP | 硬件连通性验证 |

### Real 模式要求

1. 后端已启动在 `127.0.0.1:8000`
2. ESP32 通过 TCP 已连接到后端桥接端口 (8080)
3. 硬件连接已完成（参照 `tests/HARDWARE_SETUP.md`）：
   - GPIO5 ↔ GPIO4（信号/GPIO 回路）
   - GPIO1 ↔ GPIO3（UART 回路）

## 跳过的测试

| 测试 | 原因 |
|------|------|
| `test_ws_new_connection_kicks_old` | WebSocket 单客户端踢出逻辑时序敏感，需手动验证 |
| `test_ws_send_gpio_*` (real) | WS 透传命令使用 TestClient 模拟路径 |
| `test_ws_receives_expected_state` (real) | ASGITransport 不支持 WS；real 模式手动验证 |
| `test_gpio_config` (real) | ESP32 GPIO 多次重配后不稳定，bridge 测试全覆盖 |
| `test_gpio_set` (real) | 需先 gpio_config(OUTPUT)，bridge 测试全覆盖 |
| `test_ping` (real) | CMD_PING 固件未实现，bridge 测试覆盖 |
| `test_sync_confirm` (real) | CMD_SYN 固件未实现 |
| `test_thread_not_supported*` (real) | Thread 固件未启用 |
| `test_port_unbind` (real) | 需先 port_bind |
| `test_signal_tx` (real) | 需硬件 loopback (GPIO5↔4)，bridge 测试全覆盖 |
| `test_uart_send` (real) | 需先 uart_config，ESP32 UART ~3 次重配限制 |
| `test_uart_send_base64` (real) | 同上 |
| `test_uart_read` (real) | 同上 |

## 测试结果

### Real 设备 (ESP32-C6-DevKitM-1)

```
89 passed, 3 skipped
```

### Mock 模式

```
92 passed, 1 failed (test_ws_new_connection_kicks_old — 已知WS时序敏感)
```

### 测试文件索引

| 文件 | 覆盖范围 | 数量 |
|------|---------|------|
| `test_bridge_protocol.py` | 所有协议 dataclass from_bytes 解析 + MessageFrame + opcode 唯一性 + BLE 边界 | 33 |
| `test_bridge_events.py` | EventHandler opcode→class 分发 (22 事件) + BLE 命令 + 边界 | 25 |
| `test_ble.py` | BLE API (6) +  PIN 格式/响应结构 + 事件 to_dict (8种) + 缓存 | 18 |
| `test_ws.py` | WS 连接/命令 + event_to_dict (BLE 8种 + GPIO/UART) | 16 |
| `test_pins.py` | Pin Lock CRUD + Expected State + UART 持久化 + WS expected_state | 12 |
| `test_custom_cmd.py` | 自定义指令 CRUD + 执行 (含结构化 config) | 13 |
| `test_gpio.py` | GPIO config/set/get/adc + 保留引脚 + 边界 | 7 |
| `test_hardware.py` | 硬件配置 API + 能力检查 + Thread 不支持 | 3 |
| `test_port.py` | 端口 bind/unbind/status | 3 |
| `test_signal.py` | 信号 tx/rx/exchange + 边界 | 4 |
| `test_system.py` | 设备状态/ping/heartbeat/sync/thread | 6 |
| `test_uart.py` | UART config/send/read + base64 编码 | 5 |

### BLE 测试覆盖矩阵

| 层级 | 文件 | 覆盖内容 |
|------|------|---------|
| 协议层 | `test_bridge_protocol.py` | CmdBleStartScan/CmdBleStopScan 序列化, EventBle* 7种 from_bytes + 边界 (空列表/多peer/零RSSI/reason值) |
| 事件层 | `test_bridge_events.py` | BLE 7种事件 opcode→class 分发 + CmdBleStartScan/StopScan 序列化 |
| API 层 | `test_ble.py` | 5 个 HTTP 端点 (配对启/停, peer列表, 扫描启/停) + PIN 格式验证 + 响应结构验证 + 8种 event_to_dict |
| WS 层 | `test_ws.py` | 6 种 BLE 事件 WS 序列化 (peers_list, connected, disconnected, rssi, pairing_enabled, pairing_disabled) |
| E2E | `tests/manual_ble_e2e.py` | 本机蓝牙 bleak 连接→PIN配对→常驻→断线感知→重连恢复 (7项) |

## 已知限制

1. **UART 重配限制**：ESP32 固件 `uart_driver_delete` + `uart_driver_install` 约 3-4 次后不稳定。Bridge 测试（`tests/` 根目录）使用每次新建 TCP 连接绕过此限制，覆盖更完整的 UART 测试。

2. **Thread 透传**：ESP32-C6 硬件支持 Thread 但固件未启用，`/api/v1/thread/passthrough` 返回 502。

3. **WS 命令路径**：Real 模式下 WS 命令测试跳过（`test_ws.py`），因为这些测试使用 TestClient 的 WebSocket 模拟，与真实 WS 握手不同。
