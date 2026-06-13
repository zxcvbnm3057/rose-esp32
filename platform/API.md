# Platform API 文档

本文档描述 `platform` 层当前暴露的 HTTP API 与 WebSocket 接口。

- Base URL: `http://127.0.0.1:8000`
- REST 前缀: `/api/v1`
- WebSocket: `ws://127.0.0.1:8000/ws`

---

## 1. 通用约定

### 1.1 统一返回结构

除 WebSocket 外，所有 HTTP 接口统一返回 `ApiResponse`：

```json
{
  "success": true,
  "data": {},
  "error": null,
  "timestamp": 1710000000.123
}
```

字段说明：

| 字段 | 类型 | 说明 |
|------|------|------|
| `success` | `bool` | 请求是否成功 |
| `data` | `any` | 业务数据；失败时通常为 `null` |
| `error` | `string \| null` | 错误说明 |
| `timestamp` | `float` | 服务器时间戳（秒） |

### 1.2 常见错误码

| HTTP 状态码 | 场景 |
|------------|------|
| `400` | 请求体非法，例如 base64 错误、缺少必要字段 |
| `403` | 资源被保护，例如 GPIO 为保留引脚 |
| `404` | 资源不存在，例如 GPIO 不在硬件配置中、命令 slug 不存在 |
| `409` | 资源冲突，例如自定义命令 slug 重复 |
| `422` | 参数校验失败（Pydantic） |
| `501` | 当前硬件/固件不支持对应能力 |
| `502` | bridge 命令失败、超时、设备未按预期返回 |
| `503` | ESP32 当前未连接 |

### 1.3 能力判断

部分接口会依赖硬件能力开关，例如：

- `gpio`
- `adc`
- `signal`
- `uart`
- `ble`
- `thread`

不支持时返回 `501`。

---

## 2. Hardware

### 2.1 获取硬件配置

- **方法**: `GET`
- **路径**: `/api/v1/hardware/config`
- **功能**: 返回完整硬件配置（芯片信息、引脚定义、能力开关等）
- **请求参数**: 无

**返回 `data`**

> 返回 `hardware_config.json` 的完整内容，结构取决于当前配置文件。

---

## 3. GPIO

### 3.1 配置 GPIO

- **方法**: `POST`
- **路径**: `/api/v1/gpio/{gpio}/config`
- **功能**: 配置某个 GPIO 的模式/上下拉/边沿触发

**路径参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `gpio` | `int` | 目标 GPIO 编号 |

**请求体**

```json
{
  "mode": 1,
  "pull": 0,
  "edge": 0
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `mode` | `int` | `0=INPUT 1=OUTPUT 2=INTERRUPT 3=ADC 4=SIGNAL` |
| `pull` | `int` | `0=NONE 1=DOWN 2=UP` |
| `edge` | `int` | 边沿模式，范围 `0..3` |

**返回 `data`**

```json
{
  "gpio": 5,
  "mode": 1
}
```

**备注**

- 若引脚在硬件配置中标记为 `reserved`，返回 `403`
- 若 `gpio` 不存在于硬件配置，返回 `404`

### 3.2 设置 GPIO 输出

- **方法**: `POST`
- **路径**: `/api/v1/gpio/{gpio}/set`
- **功能**: 设置 GPIO 输出电平

**请求体**

```json
{
  "value": 1
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `value` | `int` | `0` 或 `1` |

**返回 `data`**

```json
{
  "gpio": 5,
  "value": 1
}
```

**副作用**

- 成功后会通过 WebSocket 广播 `gpio_value` 事件

### 3.3 读取 GPIO

- **方法**: `GET`
- **路径**: `/api/v1/gpio/{gpio}/get`
- **功能**: 读取 GPIO 当前值

**返回 `data`**

```json
{
  "gpio": 5,
  "value": 0
}
```

### 3.4 ADC 采样

- **方法**: `POST`
- **路径**: `/api/v1/gpio/{gpio}/adc`
- **功能**: 对 GPIO 执行 ADC 采样

**请求体**

```json
{
  "samples": 4
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `samples` | `int` | 采样次数，范围 `1..16` |

**返回 `data`**

```json
{
  "gpio": 2,
  "value": 2048,
  "voltage_mv": 1650.4
}
```

---

## 4. Signal（微秒级波形 / bit-bang 类能力）

> 这一组接口暴露的是**通用微秒级波形能力**，而不是特定的 I2C 协议语义接口。可用于 bit-bang I2C / 1-Wire / 自定义时序。

### 4.1 输出波形（TX）

- **方法**: `POST`
- **路径**: `/api/v1/gpio/{gpio}/signal/tx`
- **功能**: 在指定 GPIO 上按边沿序列输出微秒级波形

**请求体**

```json
{
  "signal": [
    { "level": 1, "duration_us": 5 },
    { "level": 0, "duration_us": 5 },
    { "level": 1, "duration_us": 10 }
  ],
  "delay_us": 0
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `signal` | `SignalEdge[]` | 波形边沿列表，最多 `256` 段 |
| `delay_us` | `int` | 输出前延迟 |

`SignalEdge`:

| 字段 | 类型 | 说明 |
|------|------|------|
| `level` | `int` | `0` 或 `1` |
| `duration_us` | `int` | 持续时间（微秒），范围 `1..1_000_000` |

**返回 `data`**

```json
{
  "gpio": 5,
  "edges_sent": 3
}
```

### 4.2 采集波形（RX）

- **方法**: `POST`
- **路径**: `/api/v1/gpio/{gpio}/signal/rx`
- **功能**: 采集某个 GPIO 上的波形边沿

**请求体**

```json
{
  "timeout_us": 1000000,
  "max_edges": 100,
  "resolution": "normal"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `timeout_us` | `int` | 超时时间（微秒） |
| `max_edges` | `int` | 最多采集边沿数，范围 `1..256` |
| `resolution` | `int \| string \| null` | 软件分辨率；可传预设名或微秒值 |

**返回 `data`**

```json
{
  "gpio": 4,
  "edge_count": 2,
  "edges": [
    { "level": 1, "duration_us": 100 },
    { "level": 0, "duration_us": 200 }
  ]
}
```

### 4.3 波形交换（TX + RX）

- **方法**: `POST`
- **路径**: `/api/v1/gpio/{gpio}/signal/exchange`
- **功能**: 先发送一段波形，再在同 GPIO 上采集返回波形

**请求体**

```json
{
  "tx_signal": [
    { "level": 1, "duration_us": 5 },
    { "level": 0, "duration_us": 5 }
  ],
  "delay_us": 0,
  "rx_total_us": 500000,
  "rx_max_edges": 100,
  "resolution": 20
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `tx_signal` | `SignalEdge[]` | 发出的波形 |
| `delay_us` | `int` | 发完后到采集前的延迟 |
| `rx_total_us` | `int` | 采集窗口总时长 |
| `rx_max_edges` | `int` | 最多返回边沿数 |
| `resolution` | `int \| string \| null` | 软件毛刺合并分辨率 |

**返回 `data`**

```json
{
  "gpio": 5,
  "edge_count": 1,
  "edges": [
    { "level": 1, "duration_us": 153 }
  ]
}
```

### 4.4 获取分辨率预设

- **方法**: `GET`
- **路径**: `/api/v1/gpio/signal/resolutions`
- **功能**: 列出可用的 signal 软件分辨率预设

**返回 `data`**

```json
{
  "presets": [
    { "name": "exact", "resolution_us": 1 },
    { "name": "fine", "resolution_us": 5 },
    { "name": "normal", "resolution_us": 20 },
    { "name": "coarse", "resolution_us": 100 }
  ],
  "default": "exact"
}
```

**备注**

- 当前 resolution 是在 bridge/client 软件层做的**毛刺合并**，不是芯片内部可变滤波器
- `exact` = 最细粒度

---

## 5. UART

### 5.1 配置 UART

- **方法**: `POST`
- **路径**: `/api/v1/uart/{uart_id}/config`
- **功能**: 配置 UART 参数

**路径参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `uart_id` | `int` | UART 编号 |

**请求体**

```json
{
  "baudrate": 115200,
  "data_bits": 8,
  "parity": 0,
  "stop_bits": 1,
  "tx_gpio": 1,
  "rx_gpio": 3
}
```

**返回 `data`**

```json
{
  "uart_id": 0,
  "baudrate": 115200
}
```

### 5.2 UART 发送

- **方法**: `POST`
- **路径**: `/api/v1/uart/{uart_id}/send`
- **功能**: 发送 UART 数据

**请求体（二选一）**

```json
{
  "data": "hello",
  "encoding": "utf-8"
}
```

或

```json
{
  "data_base64": "aGVsbG8="
}
```

**返回 `data`**

```json
{
  "uart_id": 0,
  "bytes_sent": 5
}
```

### 5.3 UART 读取

- **方法**: `GET`
- **路径**: `/api/v1/uart/{uart_id}/read?length=256`
- **功能**: 读取 UART 数据

**查询参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `length` | `int` | 读取上限，范围 `1..4096` |

**返回 `data`**

```json
{
  "uart_id": 0,
  "data_base64": "aGVsbG8=",
  "length": 5
}
```

---

## 6. Port

### 6.1 绑定端口

- **方法**: `POST`
- **路径**: `/api/v1/port/bind`
- **功能**: 绑定一个 GPIO/UART 资源

**请求体**

```json
{
  "resource_type": 0,
  "id": 5,
  "owner_id": 0
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `resource_type` | `int` | `0=GPIO 1=UART` |
| `id` | `int` | 资源 ID |
| `owner_id` | `int` | 资源所有者 ID |

**返回 `data`**

```json
{
  "resource_type": 0,
  "id": 5
}
```

### 6.2 解绑端口

- **方法**: `POST`
- **路径**: `/api/v1/port/unbind`
- **功能**: 解绑 GPIO/UART 资源

**请求体**

```json
{
  "resource_type": 0,
  "id": 5
}
```

**返回 `data`**

```json
{
  "resource_type": 0,
  "id": 5
}
```

### 6.3 查询端口状态

- **方法**: `GET`
- **路径**: `/api/v1/port/status?resource_type=0&id=5`
- **功能**: 查询资源当前状态

**返回 `data`**

```json
{
  "resource_type": 0,
  "id": 5,
  "in_use": 1,
  "mode": 1,
  "value": 1
}
```

---

## 7. BLE

### 7.1 启用配对

- **方法**: `POST`
- **路径**: `/api/v1/ble/pairing/enable`
- **功能**: 进入 BLE 配对窗口

**请求体**

```json
{
  "timeout_s": 60
}
```

**返回 `data`**

```json
{
  "pin_code": "123456",
  "timeout_s": 60
}
```

### 7.2 禁用配对

- **方法**: `POST`
- **路径**: `/api/v1/ble/pairing/disable`
- **功能**: 关闭 BLE 配对窗口

**返回 `data`**

```json
{
  "pairing_disabled": true
}
```

### 7.3 获取已连接 BLE 设备

- **方法**: `GET`
- **路径**: `/api/v1/ble/peers`
- **功能**: 获取当前 BLE peer 列表

**返回 `data`**

```json
{
  "peers": [
    { "mac": "AA:BB:CC:DD:EE:FF", "rssi": -45 }
  ]
}
```

### 7.4 开始扫描

- **方法**: `POST`
- **路径**: `/api/v1/ble/scan/start`
- **功能**: 开始 BLE 扫描 / RSSI 更新

**请求体**

```json
{
  "interval_s": 5
}
```

**返回 `data`**

```json
{
  "scan_started": true
}
```

### 7.5 停止扫描

- **方法**: `POST`
- **路径**: `/api/v1/ble/scan/stop`
- **功能**: 停止 BLE 扫描

**返回 `data`**

```json
{
  "scan_stopped": true
}
```

### 7.6 BLE 设备名称映射

#### 列表
- **方法**: `GET`
- **路径**: `/api/v1/ble/device-names`
- **功能**: 获取 BLE MAC → 显示名称映射

**返回 `data`**

```json
{
  "names": [
    { "mac": "AA:BB:CC:DD:EE:FF", "name": "客厅传感器" }
  ]
}
```

#### 新建 / 更新
- **方法**: `PUT`
- **路径**: `/api/v1/ble/device-names/{mac}`
- **请求体**

```json
{ "name": "客厅传感器" }
```

**返回 `data`**

```json
{ "mac": "AA:BB:CC:DD:EE:FF", "name": "客厅传感器" }
```

#### 删除
- **方法**: `DELETE`
- **路径**: `/api/v1/ble/device-names/{mac}`

**返回 `data`**

```json
{ "mac": "AA:BB:CC:DD:EE:FF", "deleted": true }
```

---

## 8. System

### 8.1 设备连接状态

- **方法**: `GET`
- **路径**: `/api/v1/device/status`
- **功能**: 获取 platform 视角的设备连接状态

**返回 `data`**

```json
{
  "connected": true,
  "io_snapshot": {
    "gpios": [],
    "uarts": [],
    "ble": {
      "pairing_enabled": false,
      "scan_enabled": false,
      "peer_count": 0
    }
  }
}
```

### 8.2 Ping

- **方法**: `POST`
- **路径**: `/api/v1/system/ping`
- **功能**: 向固件发送 ping

**返回 `data`**

```json
{ "pong": true }
```

### 8.3 Heartbeat

- **方法**: `POST`
- **路径**: `/api/v1/system/heartbeat`
- **功能**: 请求设备 heartbeat / 连接状态

**返回 `data`**

```json
{ "connection_state": 0 }
```

### 8.4 请求同步

- **方法**: `POST`
- **路径**: `/api/v1/system/sync`
- **功能**: 请求设备推送完整状态快照

**返回 `data`**

```json
{ "session_version": 42 }
```

### 8.5 确认同步阶段

- **方法**: `POST`
- **路径**: `/api/v1/system/sync/confirm`
- **功能**: 确认某个同步阶段已完成

**请求体**

```json
{
  "correlation_id": 123,
  "stage": 0
}
```

**返回 `data`**

```json
{ "correlation_id": 123 }
```

### 8.6 Thread 透传

- **方法**: `POST`
- **路径**: `/api/v1/thread/passthrough`
- **功能**: 向 Thread 设备做原始透传（当前能力通常未启用）

**请求体**

```json
{
  "device_id": 1,
  "correlation_id": 0,
  "payload": "AQIDBA=="
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `payload` | `string` | base64 编码字节串 |

**返回 `data`**

```json
{ "device_id": 1 }
```

---

## 9. Pins（持久化预期状态）

> 这一组接口是平台层的**持久化与期望状态管理**，不直接操作硬件输出，而是记录用户/系统对引脚与 UART 的期望配置。

### 9.1 获取所有锁与持久化 UART 配置

- **方法**: `GET`
- **路径**: `/api/v1/pins/locks`
- **功能**: 返回所有持久化 pin 锁状态与 UART 配置

**返回 `data`**

```json
{
  "pins": [
    {
      "gpio": 4,
      "locked": true,
      "expected_mode": 1,
      "expected_value": 1
    }
  ],
  "uarts": [
    {
      "uart_id": 0,
      "baudrate": 115200,
      "tx_gpio": 1,
      "rx_gpio": 3,
      "data_bits": 8,
      "parity": 0,
      "stop_bits": 1
    }
  ]
}
```

### 9.2 锁定 / 解锁引脚

- **POST** `/api/v1/pins/{gpio}/lock`
- **DELETE** `/api/v1/pins/{gpio}/lock`

**返回 `data`**

```json
{ "gpio": 4, "locked": true }
```

或

```json
{ "gpio": 4, "locked": false }
```

### 9.3 保存引脚期望状态

- **方法**: `POST`
- **路径**: `/api/v1/pins/{gpio}/expected`
- **功能**: 保存期望 mode / value / pull / edge

**请求体**

```json
{
  "expected_mode": 1,
  "expected_value": 1,
  "pull": 0,
  "edge": 0
}
```

**返回 `data`**

```json
{ "gpio": 4 }
```

> `PUT /api/v1/pins/{gpio}/expected` 当前仅占位，返回空对象，不建议使用。

### 9.4 保存 / 删除 UART 期望配置

- **POST** `/api/v1/pins/uart/{uart_id}`
- **DELETE** `/api/v1/pins/uart/{uart_id}`

**保存请求体**

```json
{
  "baudrate": 115200,
  "tx_gpio": 1,
  "rx_gpio": 3,
  "data_bits": 8,
  "parity": 0,
  "stop_bits": 1
}
```

**返回 `data`**

```json
{ "uart_id": 0 }
```

---

## 10. Custom Commands（自定义命令）

### 10.1 列表

- **方法**: `GET`
- **路径**: `/api/v1/cmds`
- **功能**: 获取所有自定义命令

**返回 `data`**

```json
{
  "commands": [
    {
      "id": 1,
      "slug": "blink",
      "name": "Blink",
      "description": "闪烁 LED",
      "enabled": true,
      "step_count": 2,
      "steps": [],
      "external_url": "/cmd/blink",
      "created_at": "2026-06-13T12:00:00",
      "updated_at": "2026-06-13T12:00:00",
      "last_executed_at": null,
      "execution_count": 0
    }
  ]
}
```

### 10.2 创建

- **方法**: `POST`
- **路径**: `/api/v1/cmds`

**请求体**

```json
{
  "slug": "blink",
  "name": "Blink",
  "description": "闪烁 LED",
  "steps": [
    {
      "step_type": "gpio_set",
      "config": {"gpio": 5, "value": 1},
      "delay_ms": 100,
      "on_error": "abort"
    }
  ]
}
```

`CustomCmdStep` 字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `step_type` | `string` | 步骤类型 |
| `config` | `object` | 步骤配置 |
| `delay_ms` | `int` | 执行后延迟 |
| `on_error` | `string` | 错误策略，默认 `abort` |

### 10.3 查询单个命令

- **方法**: `GET`
- **路径**: `/api/v1/cmds/{slug}`

### 10.4 更新命令

- **方法**: `PUT`
- **路径**: `/api/v1/cmds/{slug}`

**请求体（可部分更新）**

```json
{
  "name": "Blink 2",
  "enabled": true,
  "steps": []
}
```

### 10.5 删除命令

- **方法**: `DELETE`
- **路径**: `/api/v1/cmds/{slug}`

**返回 `data`**

```json
{ "slug": "blink", "deleted": true }
```

### 10.6 执行命令（内部 API）

- **方法**: `POST`
- **路径**: `/api/v1/cmds/{slug}/execute`

**请求体**

```json
{
  "params": {}
}
```

**返回 `data`**

```json
{
  "slug": "blink",
  "steps_executed": 1,
  "results": [],
  "duration_ms": 120
}
```

### 10.7 执行命令（公共 URL）

- **方法**: `POST`
- **路径**: `/cmd/{slug}`
- **功能**: 通过公共 URL 执行已启用命令

---

## 11. WebSocket

- **路径**: `/ws`
- **协议**: WebSocket JSON 消息
- **功能**: 实时状态推送 + 少量受限命令

### 11.1 角色模型

| 角色 | 连接方式 | 能力 |
|------|----------|------|
| `app` | `/ws` 或 `/ws?role=app` | 默认角色；只读订阅 + 只读命令 |
| `console` | `/ws?role=console` | 控制台；可订阅 + 控制命令 |

### 11.2 当前 WS 命令白名单

| op | 权限类别 | 允许角色 | 说明 |
|----|----------|----------|------|
| `gpio_get` | `read` | `app`, `console` | 读取 GPIO |
| `adc_sample` | `read` | `app`, `console` | 读取 ADC |
| `gpio_set` | `control` | `console` | 设置 GPIO 输出 |

> 未登记命令（如 `gpio_config`）会返回 `Unknown or unsupported WS op`。

### 11.3 连接后初始消息

新连接通常会收到以下初始化消息（视缓存/状态而定）：

1. `hardware_config`
2. `connection_change`
3. `expected_state`（若数据库里有持久化状态）
4. `device_state`（若平台已有缓存）

### 11.4 常见事件类型

| type | 说明 |
|------|------|
| `hardware_config` | 硬件配置 |
| `connection_change` | 设备连接状态变化 |
| `expected_state` | 平台持久化的预期状态 |
| `device_state` | 平台缓存的设备状态快照 |
| `gpio_value` | GPIO 值变化 |
| `gpio_status` | GPIO 状态同步事件 |
| `gpio_edge` | GPIO 边沿事件 |
| `adc_value` | ADC 值事件 |
| `signal_captured` | 波形采集结果 |
| `uart_rx` | UART 收到数据（base64） |
| `uart_status` | UART 状态同步 |
| `port_status` | 端口状态同步 |
| `ble_status` | BLE 总体状态 |
| `ble_pairing_enabled` | BLE 配对开启 |
| `ble_pairing_disabled` | BLE 配对关闭 |
| `ble_peers_list` | BLE 已连接设备列表 |
| `ble_peer_connected` | BLE 新连接 |
| `ble_peer_disconnected` | BLE 断开 |
| `ble_rssi` | BLE RSSI 更新 |
| `heartbeat` | 心跳事件 |
| `error` | bridge/error 事件 |
| `cmd_result` | WS 指令执行结果 |

### 11.5 `cmd_result` 消息格式

```json
{
  "type": "cmd_result",
  "op": "gpio_get",
  "success": true,
  "data": {
    "value": 0
  }
}
```

失败示例：

```json
{
  "type": "cmd_result",
  "op": "gpio_set",
  "success": false,
  "error": "Operation 'gpio_set' is not allowed for role 'app'"
}
```

---

## 12. 设计说明

- `platform` 是公共底层：负责 bridge、REST、WebSocket、缓存、持久化
- `console` 是硬件操作界面：显式使用 `?role=console`
- `app` 是上层业务后端：默认通过 `/ws` 接入，只读订阅，不改配硬件
- 微秒级波形能力通过 `signal/tx`、`signal/rx`、`signal/exchange` 暴露，而非单独的 I2C 语义接口
