# IoT Agent 测试板上 IO 连接要求

## 概述

为了充分测试 ESP32 IoT Agent 的所有功能，采用自循环测试设计，最大限度复用 GPIO 引脚以减少接线复杂度。所有测试（除 ADC 需要外部电位器外）均使用内部 GPIO 循环，无需外部设备。

### 测试文件总览

| 测试文件 | 覆盖范围 | 硬性要求 |
|----------|----------|----------|
| `test_basic.py` | 连接、Ping、心跳、GPIO 基本操作 | 无 |
| `test_edge.py` | GPIO INTERRUPT 模式边沿事件 | GPIO 5↔4 回环 |
| `test_port_status.py` | 端口绑定/解绑/状态查询 | 无 |
| `test_adc.py` | ADC 采样、值范围、事件结构 | GPIO 6 接电压源 |
| `test_uart.py` | UART 事件驱动 RX、回环、轮询读取 | UART TX↔RX 回环 |
| `test_signal.py` | GPIO 信号 TX/RX/Exchange | GPIO 5↔4 回环 |
| `test_ble.py` | BLE 配对、Peer 列表、RSSI 扫描 | BLE 支持 |
| `test_ble_events.py` | BLE 连接/断开事件、RSSI 周期 | BLE + 外部设备 |
| `test_sync.py` | SYNC_REQUEST/RESPONSE、SYN 确认、重连 | 无 |
| `test_reconnect.py` | TCP 断连重连、sync 恢复 | 无 |
| `test_thread.py` | Thread 透传错误处理、双向通信 | Thread 设备 |
| `test_integration.py` | GPIO+UART 并发、压力测试 | GPIO 5↔4 回环 |
| `test_gpio.py` | GPIO 详细操作 | GPIO 5↔4 回环 |

## 核心 GPIO 复用连接

### GPIO 5 ↔ GPIO 4 (多功能复用)
```
ESP32 GPIO 连接：
GPIO 5 ────────────────── GPIO 4
   │                          │
   ├─── 数字输出测试          ├─── 数字输入测试
   ├─── 信号 TX 测试          ├─── 信号 RX 测试
   └─── 信号交换测试          └─── 信号捕获测试
```

**复用功能**：
- **GPIO 测试**：GPIO 5 输出 → GPIO 4 输入
- **信号测试**：GPIO 5 TX → GPIO 4 RX（信号循环）
- **ADC 测试**：GPIO 6 连接外部电位器

**测试覆盖**：
- `test_gpio_loopback` (GPIO 基本功能)
- `test_signal_tx_rx_loopback_complete` (信号收发回路)
- `test_signal_exchange_timing` (信号交换)

### ADC 测试连接
```
ESP32 GPIO 连接：
GPIO 6 ─────── 可调电压源 (0-3.3V)
```

**用途**：测试 ADC 采样功能
**测试**：`test_adc_sampling`
**要求**：电位器分压电路（3.3V → GND，中间抽头接 GPIO 6）

## UART 自循环测试

### UART0 内部循环
```
ESP32 GPIO 连接：
GPIO 1 (UART0 TX) ────── GPIO 3 (UART0 RX)
```

**用途**：UART 发送/接收自循环测试
**测试**：UART 功能完整测试
**优势**：无需外部设备，完全自包含

## BLE 测试要求

### BLE 软件测试
```
无需物理连接，完全软件验证：
- 配对模式启用/禁用
- Peer 列表查询
- RSSI 扫描功能
- 连接状态监控
```

**测试**：`tests/test_ble.py` 中的所有测试
**要求**：ESP32 支持 BLE（ESP32-C3/C6/WROOM-32 等）

## 最小化连接示意图

```
ESP32-DevKitC 开发板最小连接：

+---------------------+
| ESP32-DevKitC       |
|                     |
| GPIO 5 ──●─────────┼─ GPIO 4
|         │          │
|         ├── GPIO 测试  │
|         ├── 信号测试   │
|         └── ADC 测试   │
|                     │
| GPIO 6 ──●─────────┼─ 电位器中间端
|         │          │
| GPIO 1 ──●─────────┼─ GPIO 3  (UART 循环)
|         │          │
|  [BLE 功能]        │
|  - 纯软件测试      │
+---------------------+

外部电位器电路：
3.3V ──[10KΩ电位器]── GND
            │
            └── GPIO 6
```

## 连接步骤

1. **准备材料**：
   - ESP32 开发板（支持 BLE）
   - 3根杜邦线
   - 1个 10KΩ 电位器

2. **建立核心连接**：
   ```bash
   # GPIO 5 ↔ GPIO 4 (多功能复用)
   连接 GPIO 5 到 GPIO 4

   # GPIO 1 ↔ GPIO 3 (UART 自循环)
   连接 GPIO 1 到 GPIO 3
   ```

3. **ADC 测试电路**：
   ```bash
   # 电位器连接
   电位器一端接 3.3V
   电位器另一端接 GND
   电位器中间端接 GPIO 6
   ```

4. **验证连接**：
   ```bash
   # 运行完整测试套件
   pytest tests/ -v --tb=short

   # 按类别运行
   pytest tests/test_basic.py tests/test_edge.py tests/test_port_status.py -v
   pytest tests/test_signal.py tests/test_uart.py tests/test_adc.py -v
   pytest tests/test_ble.py tests/test_ble_events.py tests/test_sync.py -v
   pytest tests/test_reconnect.py tests/test_thread.py tests/test_integration.py -v

   # 跳过硬相关测试
   SKIP_BLE_CONNECT_TESTS=1 pytest tests/ --ignore=tests/test_uart.py --ignore=tests/test_ble.py --ignore=tests/test_ble_events.py -v

   # 启用需硬件的测试
   RUN_ADC_TESTS=1 pytest tests/test_adc.py -v
   # UART: 先接好 GPIO 1↔3 回环，再跑
   pytest tests/test_uart.py -v
   # BLE 连接: PC 蓝牙开启 + ESP32 广播中
   pytest tests/test_ble_events.py -v
   ```

## 测试执行顺序

### Phase 1: 基础功能测试
1. **GPIO 基本功能** (`test_basic.py`):
   - 连接测试、Ping/Heartbeat
   - GPIO 输出/输入测试
   - GPIO 配置、设置、读取

2. **GPIO 边沿中断** (`test_edge.py`):
   - INTERRUPT 模式边沿事件验证
   - 边沿计数匹配翻转次数
   - INPUT 模式不产生边沿事件

3. **ADC 采样** (`test_adc.py`):
   - 单次/多次采样
   - 值范围验证 (0-4095)
   - 无效 GPIO 拒绝

4. **端口状态** (`test_port_status.py`):
   - GPIO/UART 端口绑定/解绑生命周期
   - PORT_STATUS 严格字段断言
   - 重复绑定拒绝、未绑定端口解绑

### Phase 2: 通讯功能测试
5. **UART 自循环** (`test_uart.py`):
   - 配置测试、事件驱动 RX (listener)
   - 发送/接收回环验证
   - 传统轮询读取路径

6. **信号处理** (`test_signal.py`):
   - TX/RX 循环测试
   - 信号交换测试
   - 时序精度验证
   - 最大边沿数量限制

### Phase 3: 无线功能测试
7. **BLE 功能** (`test_ble.py`, `test_ble_events.py`):
   - 配对启用/禁用流程
   - Peer 列表结构验证
   - RSSI 扫描事件周期
   - 连接/断开事件 (需外部 BLE 设备)

### Phase 4: 集成与同步测试
8. **同步协议** (`test_sync.py`):
   - SYNC_RESPONSE 结构验证
   - SYN stage 0/1 确认
   - 重连后 session version 递增
   - 端口状态快照

9. **断连重连** (`test_reconnect.py`):
   - 连接丢失后自动恢复
   - SYNC_REQUEST 在掉线期间不挂死
   - 恢复后 sync 状态可用

10. **Thread 透传** (`test_thread.py`):
   - 无设备时报告错误
   - 在线设备双向透传 (需 Thread 设备)

11. **并发操作** (`test_integration.py`):
   - 多 GPIO 同时操作
   - UART + GPIO 并发
   - 性能压力测试

## IO 复用策略

### GPIO 5/4 复用方案
- **测试前**：配置为 GPIO 模式进行数字 IO 测试
- **测试中**：动态切换到信号模式进行 RMT 测试
- **测试后**：恢复 GPIO 模式进行验证

### 动态配置示例
```python
# GPIO 模式测试
client.configure_gpio(5, GPIO_MODE_OUTPUT)
client.configure_gpio(4, GPIO_MODE_INPUT)
client.set_gpio(5, 1)
value = client.get_gpio(4)

# 信号模式测试 (复用同一引脚对)
signal = [(1, 100), (0, 200), (1, 150)]
result = client.exchange_signals(5, signal, rx_gpio=4)
```

## 注意事项

- **电源安全**：所有连接使用 3.3V 逻辑电平
- **引脚兼容性**：确认 ESP32 型号支持所有使用的 GPIO
- **BLE 支持**：选择支持 BLE 的 ESP32 型号 (C3/C6/WROOM-32等)
- **电位器规格**：使用 10KΩ 线性电位器，额定电压 3.3V
- **连接顺序**：先连接 GPIO 循环，再连接 ADC，最后上电

## 故障排除

### GPIO 信号问题
- **现象**：信号测试失败
- **检查**：确认 GPIO 5 和 GPIO 4 正确连接
- **解决**：用万用表验证连接连续性

### ADC 读数异常
- **现象**：ADC 值不随电位器变化
- **检查**：电位器连接正确性，电压范围 0-3.3V
- **解决**：检查电位器是否损坏，更换新电位器

### UART 通讯失败
- **现象**：UART 自循环测试失败
- **检查**：GPIO 1 和 GPIO 3 连接，UART0 未被占用
- **解决**：确认引脚未被其他功能使用

### BLE 功能异常
- **现象**：BLE 测试失败
- **检查**：ESP32 型号支持 BLE，固件包含 BLE 功能
- **解决**：更换支持 BLE 的 ESP32 开发板

## 优势总结

- **接线最少**：仅 3 根杜邦线 + 1 个电位器
- **完全自包含**：除 ADC 外无需外部设备
- **测试全面**：覆盖所有 25 个命令功能
- **易于搭建**：5 分钟内完成所有连接
- **可靠性高**：减少外部连接的不确定性