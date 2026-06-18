# Bridge 测试运行说明

本目录包含 IoT Agent 桥接层（`bridge/src`）的全部测试：协议/事件单元测试（无需硬件）
与真实 ESP32 硬件测试。

## 工作目录（重要）

> **所有测试命令都必须在仓库根目录 `e:\CodeSpace\rose-esp32` 下执行。**

原因：`conftest.py` 与各测试用相对导入引用被测代码（`from ..src import IoTAgentClient`），
因此 `bridge` 必须作为 Python 包被发现。`pytest` 通过包路径 `bridge/tests/...` 收集用例。

不要 `cd bridge/tests` 再运行 `pytest`，那样相对导入会失败（`ImportError: attempted relative import`）。

```powershell
# 正确：在仓库根目录
cd e:\CodeSpace\rose-esp32
python -m pytest bridge/tests/ -q
```

## 两种测试模式

| 模式 | 环境变量 | 说明 | 适合 |
|------|---------|------|------|
| **单元测试** | 默认（不设） | 仅跑协议/事件解析等纯逻辑，硬件测试自动 skip | CI、快速验证 |
| **硬件测试** | `USE_REAL_DEVICE=1` | 连接真实 ESP32（TCP）跑完整套件 | 硬件连通性验证 |

硬件测试前置条件：
1. ESP32 已上电并通过 TCP 连接到 PC 上的桥接服务端（:8080）。
2. 回环接线已完成（参见 `HARDWARE_SETUP.md`）：GPIO5 ↔ GPIO4、GPIO1 ↔ GPIO3。
3. BLE 配对测试需要 Windows 蓝牙开启 + 开发者模式（用于 `winrt` 无弹窗注入 PIN）。

## 常用命令（PowerShell）

```powershell
# ── 仅单元测试（无需硬件）──────────────────────────────
python -m pytest bridge/tests/test_protocol_commands.py `
                 bridge/tests/test_protocol_events.py `
                 bridge/tests/test_protocol_frame.py `
                 bridge/tests/test_bridge_protocol.py `
                 bridge/tests/test_bridge_events.py `
                 bridge/tests/test_server_lifecycle.py -q

# ── 完整硬件套件（含全自动 BLE 配对）─────────────────────
$env:USE_REAL_DEVICE="1"
python -m pytest bridge/tests/ -p no:cacheprovider -q

# ── 仅 BLE（配对/连接/断开/RSSI，全自动）─────────────────
$env:USE_REAL_DEVICE="1"
python -m pytest bridge/tests/test_ble.py bridge/tests/test_ble_events.py -q

# ── 按类别（硬件）──────────────────────────────────────
$env:USE_REAL_DEVICE="1"
python -m pytest bridge/tests/test_basic.py bridge/tests/test_edge.py bridge/tests/test_port_status.py -q
python -m pytest bridge/tests/test_signal.py bridge/tests/test_uart.py bridge/tests/test_adc.py -q
python -m pytest bridge/tests/test_sync.py bridge/tests/test_reconnect.py -q
```

> **环境变量作用域**：PowerShell 中 `$env:USE_REAL_DEVICE="1"` 仅对当前会话生效。
> 跑完单元测试想切回纯单元模式时执行 `Remove-Item Env:\USE_REAL_DEVICE`。

### 可选开关

| 环境变量 | 取值 | 作用 |
|---------|------|------|
| `USE_REAL_DEVICE` | `1` | 启用硬件测试（不设则 skip） |
| `SKIP_BLE_CONNECT_TESTS` | `1` | 可选 opt-out，跳过 BLE 连接/配对测试（默认已全自动，无需设置） |

## BLE 测试已全自动

BLE 配对/连接测试通过 `winrt` 的 `DeviceInformationCustomPairing` 无弹窗注入固件下发的
6 位 PIN，无需人工在 Windows 弹窗输入。`winrt` 不可用时相关测试自动 skip。
连续配对周期偶发的 `status=19`（WinRT 通用失败）已通过 `ble_helper.pair_with_pin` 的
重试机制（最多 3 次，失败先解绑再等待）消除。

## 测试文件总览

| 测试文件 | 覆盖范围 | 硬件要求 |
|----------|----------|----------|
| `test_protocol_commands.py` | 命令序列化 + opcode 值 | 无 |
| `test_protocol_frame.py` | framing + CRC16 | 无 |
| `test_protocol_events.py` | 全事件解析 + EventHandler 分发 | 无 |
| `test_bridge_protocol.py` | dataclass from_bytes + MessageFrame + BLE 边界 | 无 |
| `test_bridge_events.py` | EventHandler opcode→class 分发 + BLE 命令 | 无 |
| `test_server_lifecycle.py` | 端口释放/rebind/线程 join/双重 stop | 无 |
| `test_basic.py` | 连接、Ping、心跳、GPIO 基本操作 | 无 |
| `test_edge.py` | GPIO INTERRUPT 边沿事件 | GPIO 5↔4 |
| `test_port_status.py` | 端口绑定/解绑/状态查询 | 无 |
| `test_adc.py` | ADC 采样、值范围、事件结构 | GPIO 6 接电压源 |
| `test_uart.py` | UART 事件驱动 RX、回环、轮询读取、未绑定 UART 拒绝 send/read | GPIO 1↔3 |
| `test_signal.py` | GPIO 信号 TX/RX/Exchange | GPIO 5↔4 |
| `test_gpio.py` | GPIO 详细操作、未绑定 GPIO 拒绝 set、UART 占用引脚拒绝 set | GPIO 5↔4 |
| `test_ble.py` | BLE 配对、Peer 列表、RSSI 扫描（全自动） | BLE |
| `test_ble_events.py` | BLE 连接/断开事件、RSSI 周期（全自动） | BLE |
| `test_sync.py` | SYNC_REQUEST/RESPONSE、SYN 确认 | 无 |
| `test_reconnect.py` | TCP 断连重连、sync 恢复 | 无 |
| `test_thread.py` | Thread 透传错误处理、双向通信 | Thread 设备 |
| `test_integration.py` | GPIO+UART 并发、压力测试 | GPIO 5↔4 |

接线细节、引脚复用方案与故障排除见 `HARDWARE_SETUP.md`。
