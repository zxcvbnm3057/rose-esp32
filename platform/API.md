# Platform API 文档（含可用范围）

本文档描述 `platform` 当前暴露的 HTTP API 与 WebSocket 接口，并为**每个接口**标明可用范围。

- Base URL: `http://127.0.0.1:8000`
- REST 前缀: `/api/v1`
- WebSocket: `ws://127.0.0.1:8000/ws`

---

## 1. 通用约定

### 1.1 统一返回结构

所有 HTTP 接口统一返回：

```json
{
  "success": true,
  "data": {},
  "error": null,
  "timestamp": 1710000000.123
}
```

### 1.2 可用范围标记

本文档为每个接口标注可用范围：

| 标记 | 含义 |
|------|------|
| `console` | 面向硬件操作界面 |
| `app` | 面向上层业务后端 |
| `internal` | 平台内部/受限能力，不建议业务层直接依赖 |
| `public` | 可公开调用 |

### 1.3 常见错误码

| HTTP 状态码 | 场景 |
|------------|------|
| `400` | 请求体非法，例如 base64 错误、缺少必要字段 |
| `403` | 资源被保护，例如 GPIO 为保留引脚 |
| `404` | 资源不存在，例如 GPIO 不在硬件配置中、命令 slug 不存在 |
| `409` | 资源冲突，例如自定义命令 slug 重复 |
| `422` | 参数校验失败 |
| `501` | 当前硬件/固件不支持对应能力 |
| `502` | bridge 命令失败、超时、设备未按预期返回 |
| `503` | ESP32 当前未连接 |

---

## 2. Hardware

### GET `/api/v1/hardware/config`
- **功能**：返回完整硬件配置
- **可用范围**：`console`, `app`
- **入参**：无
- **返回 `data`**：`hardware_config.json` 的完整内容

---

## 3. GPIO

### POST `/api/v1/gpio/{gpio}/config`
- **功能**：配置 GPIO 模式/上下拉/边沿
- **可用范围**：`console`
- **路径参数**：`gpio: int`
- **请求体**：
  - `mode: int` (`0=INPUT 1=OUTPUT 2=INTERRUPT 3=ADC 4=SIGNAL 5=INPUT_OUTPUT`)
  - `pull: int` (`0=NONE 1=DOWN 2=UP`)
  - `edge: int` (`0..3`)
- **返回 `data`**：`{ "gpio": int, "mode": int }`
- **备注**：保留引脚返回 `403`；未知 GPIO 返回 `404`

### POST `/api/v1/gpio/{gpio}/set`
- **功能**：设置 GPIO 输出电平
- **可用范围**：`console`
- **路径参数**：`gpio: int`
- **请求体**：`{ "value": 0|1 }`
- **返回 `data`**：`{ "gpio": int, "value": 0|1 }`
- **备注**：仅允许已绑定且模式为 `OUTPUT` / `INPUT_OUTPUT` 的 GPIO；若该引脚正被 UART 占用，也必须拒绝。成功后会广播 `gpio_value` WS 事件。

### GET `/api/v1/gpio/{gpio}/get`
- **功能**：读取 GPIO 当前值
- **可用范围**：`console`, `app`
- **路径参数**：`gpio: int`
- **返回 `data`**：`{ "gpio": int, "value": int }`

### POST `/api/v1/gpio/{gpio}/adc`
- **功能**：执行 ADC 采样
- **可用范围**：`console`, `app`
- **路径参数**：`gpio: int`
- **请求体**：`{ "samples": 1..16 }`
- **返回 `data`**：`{ "gpio": int, "value": int, "voltage_mv": float }`

---

## 4. Signal（微秒级波形 / bit-bang 类能力）

> 暴露的是**通用微秒级波形能力**，不是特定 I2C 协议语义接口。

### POST `/api/v1/gpio/{gpio}/signal/tx`
- **功能**：按边沿序列输出微秒级波形
- **可用范围**：`console`, `app`
- **路径参数**：`gpio: int`
- **请求体**：
  - `signal: [{ level, duration_us }]`（最多 256 段）
  - `delay_us: int`
- **返回 `data`**：`{ "gpio": int, "edges_sent": int }`

### POST `/api/v1/gpio/{gpio}/signal/rx`
- **功能**：采集波形边沿
- **可用范围**：`console`, `app`
- **路径参数**：`gpio: int`
- **请求体**：
  - `timeout_us: int`
  - `max_edges: int`
  - `resolution: int | string | null`
- **返回 `data`**：
  - `gpio: int`
  - `edge_count: int`
  - `edges: [{ level, duration_us }]`

### POST `/api/v1/gpio/{gpio}/signal/exchange`
- **功能**：先发送波形，再采集返回波形
- **可用范围**：`console`, `app`
- **路径参数**：`gpio: int`
- **请求体**：
  - `tx_signal: [{ level, duration_us }]`
  - `delay_us: int`
  - `rx_total_us: int`
  - `rx_max_edges: int`
  - `resolution: int | string | null`
- **返回 `data`**：
  - `gpio: int`
  - `edge_count: int`
  - `edges: [{ level, duration_us }]`

### GET `/api/v1/gpio/signal/resolutions`
- **功能**：列出 signal 软件分辨率预设
- **可用范围**：`console`, `app`
- **返回 `data`**：
  - `presets: [{ name, resolution_us }]`
  - `default: "exact"`

---

## 5. UART

### POST `/api/v1/uart/{uart_id}/config`
- **功能**：配置 UART 参数
- **可用范围**：`console`
- **路径参数**：`uart_id: int`
- **请求体**：
  - `baudrate: int`
  - `data_bits: 5..8`
  - `parity: 0..2`
  - `stop_bits: 1..2`
  - `tx_gpio: int`
  - `rx_gpio: int`
- **返回 `data`**：`{ "uart_id": int, "baudrate": int }`

### POST `/api/v1/uart/{uart_id}/send`
- **功能**：发送 UART 数据
- **可用范围**：`console`, `app`
- **路径参数**：`uart_id: int`
- **请求体（二选一）**：
  - `{ "data": "hello", "encoding": "utf-8" }`
  - `{ "data_base64": "aGVsbG8=" }`
- **返回 `data`**：`{ "uart_id": int, "bytes_sent": int }`
- **备注**：仅允许对已完整配置/绑定的 UART 发送；未绑定 UART 必须失败。

### GET `/api/v1/uart/{uart_id}/read`
- **功能**：主动读取 UART 数据
- **可用范围**：`console`, `internal`
- **路径参数**：`uart_id: int`
- **查询参数**：`length: 1..4096`
- **返回 `data`**：
  - `uart_id: int`
  - `data_base64: string`
  - `length: int`
- **备注**：仅允许对已完整配置/绑定的 UART 读取；未绑定 UART 必须失败。对 `app` 不建议使用；业务后端应通过 WebSocket `uart_rx` 事件接收 UART 数据

---

## 6. Port

### POST `/api/v1/port/bind`
- **功能**：绑定 GPIO/UART 资源
- **可用范围**：`console`
- **请求体**：`{ "resource_type": 0|1, "id": int, "owner_id": int }`
- **返回 `data`**：`{ "resource_type": int, "id": int }`

### POST `/api/v1/port/unbind`
- **功能**：解绑 GPIO/UART 资源
- **可用范围**：`console`
- **请求体**：`{ "resource_type": 0|1, "id": int }`
- **返回 `data`**：`{ "resource_type": int, "id": int }`

### GET `/api/v1/port/status`
- **功能**：查询资源状态
- **可用范围**：`console`, `internal`
- **查询参数**：`resource_type`, `id`
- **返回 `data`**：`{ "resource_type": int, "id": int, "in_use": int, "mode": int|null, "value": int|null }`
- **备注**：不面向 `app` 公开

---

## 7. BLE

### POST `/api/v1/ble/pairing/enable`
- **功能**：打开 BLE 配对窗口
- **可用范围**：`console`
- **请求体**：`{ "timeout_s": int }`
- **返回 `data`**：`{ "pin_code": string, "timeout_s": int }`

### POST `/api/v1/ble/pairing/disable`
- **功能**：关闭 BLE 配对窗口
- **可用范围**：`console`
- **返回 `data`**：`{ "pairing_disabled": true }`

### GET `/api/v1/ble/peers`
- **功能**：获取当前 BLE peer 列表
- **可用范围**：`console`, `app`
- **返回 `data`**：`{ "peers": [{ "mac": string, "rssi": int }] }`
- **备注**：`app` 更推荐通过 WebSocket 的 `ble_peers_list` / `ble_peer_connected` / `ble_peer_disconnected` / `ble_rssi` 事件订阅变化

### POST `/api/v1/ble/scan/start`
- **功能**：开始 BLE 扫描 / RSSI 更新
- **可用范围**：`console`
- **请求体**：`{ "interval_s": int }`
- **返回 `data`**：`{ "scan_started": true }`

### POST `/api/v1/ble/scan/stop`
- **功能**：停止 BLE 扫描
- **可用范围**：`console`
- **返回 `data`**：`{ "scan_stopped": true }`

### GET `/api/v1/ble/device-names`
- **功能**：获取 BLE MAC→显示名称映射
- **可用范围**：`console`, `app`
- **返回 `data`**：`{ "names": [{ "mac": string, "name": string }] }`

### PUT `/api/v1/ble/device-names/{mac}`
- **功能**：设置/更新 BLE 设备名称映射
- **可用范围**：`console`
- **请求体**：`{ "name": string }`
- **返回 `data`**：`{ "mac": string, "name": string }`

### DELETE `/api/v1/ble/device-names/{mac}`
- **功能**：删除 BLE 设备名称映射
- **可用范围**：`console`
- **返回 `data`**：`{ "mac": string, "deleted": true }`

---

## 8. System

### GET `/api/v1/device/status`
- **功能**：获取 platform 视角的设备连接状态
- **可用范围**：`console`, `internal`
- **返回 `data`**：
  - `connected: bool`
  - `io_snapshot: { gpios: [], uarts: [], ble: { pairing_enabled, scan_enabled, peer_count } }`
- **备注**：不面向 `app` 公开；`app` 应通过 WS 订阅状态变化

### POST `/api/v1/system/ping`
- **功能**：向固件发送 ping
- **可用范围**：`console`, `internal`
- **返回 `data`**：`{ "pong": true }`

### POST `/api/v1/system/heartbeat`
- **功能**：请求设备 heartbeat / 连接状态
- **可用范围**：`console`, `internal`
- **返回 `data`**：`{ "connection_state": int }`

### POST `/api/v1/system/sync`
- **功能**：请求设备推送完整状态快照
- **可用范围**：`console`, `internal`
- **返回 `data`**：`{ "session_version": int }`

### POST `/api/v1/system/sync/confirm`
- **功能**：确认同步阶段已完成
- **可用范围**：`console`, `internal`
- **请求体**：`{ "correlation_id": int, "stage": int }`
- **返回 `data`**：`{ "correlation_id": int }`

### POST `/api/v1/thread/passthrough`
- **功能**：向 Thread 设备做原始透传
- **可用范围**：`console`, `app`
- **请求体**：
  - `device_id: int`
  - `correlation_id: int`
  - `payload: string`（base64）
- **返回 `data`**：`{ "device_id": int }`

---

## 9. Pins（持久化预期状态）

> 这一组接口用于记录平台层的引脚锁与期望配置，不直接发硬件控制命令。

### GET `/api/v1/pins/locks`
- **功能**：获取所有持久化 pin 锁状态与 UART 配置
- **可用范围**：`console`, `internal`
- **返回 `data`**：
  - `pins: [{ gpio, locked, expected_mode, expected_value }]`
  - `uarts: [{ uart_id, baudrate, tx_gpio, rx_gpio, data_bits, parity, stop_bits }]`
- **备注**：`app` 不应依赖 pins 体系

### POST `/api/v1/pins/{gpio}/lock`
- **功能**：锁定引脚
- **可用范围**：`console`
- **返回 `data`**：`{ "gpio": int, "locked": true }`

### DELETE `/api/v1/pins/{gpio}/lock`
- **功能**：解锁引脚
- **可用范围**：`console`
- **返回 `data`**：`{ "gpio": int, "locked": false }`

### PUT `/api/v1/pins/{gpio}/expected`
- **功能**：预留接口 / 占位
- **可用范围**：`internal`
- **备注**：当前仅返回空对象，不建议直接使用

### POST `/api/v1/pins/{gpio}/expected`
- **功能**：保存 pin 期望 mode/value/pull/edge
- **可用范围**：`console`
- **请求体**：`{ "expected_mode": int, "expected_value": int, "pull": int, "edge": int }`
- **返回 `data`**：`{ "gpio": int }`

### POST `/api/v1/pins/uart/{uart_id}`
- **功能**：保存 UART 期望配置
- **可用范围**：`console`
- **请求体**：`{ "baudrate": int, "tx_gpio": int, "rx_gpio": int, "data_bits": int, "parity": int, "stop_bits": int }`
- **返回 `data`**：`{ "uart_id": int }`

### DELETE `/api/v1/pins/uart/{uart_id}`
- **功能**：删除持久化 UART 配置
- **可用范围**：`console`
- **返回 `data`**：`{ "uart_id": int }`

---

## 10. Custom Commands

### GET `/api/v1/cmds`
- **功能**：获取所有自定义命令
- **可用范围**：`console`, `app`
- **返回 `data`**：`{ "commands": [...] }`

### POST `/api/v1/cmds`
- **功能**：创建自定义命令
- **可用范围**：`console`
- **请求体**：`{ "slug": string, "name": string, "description": string, "steps": CustomCmdStep[] }`

### GET `/api/v1/cmds/{slug}`
- **功能**：获取单个命令详情
- **可用范围**：`console`, `app`

### PUT `/api/v1/cmds/{slug}`
- **功能**：更新命令
- **可用范围**：`console`

### DELETE `/api/v1/cmds/{slug}`
- **功能**：删除命令
- **可用范围**：`console`

### POST `/api/v1/cmds/{slug}/execute`
- **功能**：执行命令（内部 API）
- **可用范围**：`console`, `app`, `internal`
- **请求体**：`{ "params": {} }`
- **返回 `data`**：`{ "slug": string, "steps_executed": int, "results": [], "duration_ms": int }`

### POST `/cmd/{slug}`
- **功能**：通过公共 URL 执行已启用命令
- **可用范围**：`public`

---

## 11. WebSocket

- **路径**：`/ws`
- **协议**：WebSocket JSON
- **功能**：实时状态推送 + 少量受限命令

### 11.1 角色模型

| 角色 | 连接方式 | 可用范围 |
|------|----------|----------|
| `app` | `/ws` 或 `/ws?role=app` | 默认角色；只读订阅 + 允许的只读/业务命令 |
| `console` | `/ws?role=console` | 控制台；可读 + 控制命令 |

### 11.2 当前 WS 命令白名单

| op | 权限类别 | 允许角色 | 说明 |
|----|----------|----------|------|
| `gpio_get` | `read` | `app`, `console` | 读取 GPIO |
| `adc_sample` | `read` | `app`, `console` | 读取 ADC |
| `signal_tx` | `read` | `app`, `console` | 输出微秒级波形 |
| `signal_rx` | `read` | `app`, `console` | 采集波形 |
| `signal_exchange` | `read` | `app`, `console` | 发送并采集波形 |
| `uart_send` | `read` | `app`, `console` | 发送 UART 数据 |
| `thread_passthrough` | `read` | `app`, `console` | Thread 原始透传 |
| `gpio_set` | `control` | `console` | 设置 GPIO 输出 |

> 未登记命令（如 `gpio_config`、BLE 配对开关、pins 管理、status 类查询）一律返回 `Unknown or unsupported WS op`。

### 11.3 app 在 WS 上的能力边界

- **允许**：
  - `gpio_get`
  - `adc_sample`
  - `signal_tx` / `signal_rx` / `signal_exchange`
  - `uart_send`
  - `thread_passthrough`
  - BLE peer 列表与 peer 变化事件订阅
  - `uart_rx` 事件接收 UART 数据
- **不允许**：
  - `gpio_set`
  - GPIO/UART 配置与 port bind/unbind
  - BLE 配对/扫描控制
  - `pins` 体系
  - `device/status` 这类平台内部状态接口的 WS 暴露

### 11.4 初始化消息

新连接通常会收到：
1. `hardware_config`
2. `connection_change`
3. `expected_state`（若数据库有持久化状态）
4. `device_state`（若平台已有缓存）

### 11.5 常见事件类型

| type | 可用范围 | 说明 |
|------|----------|------|
| `hardware_config` | `app`, `console` | 硬件配置 |
| `connection_change` | `app`, `console` | 设备连接状态变化 |
| `expected_state` | `console` 为主 | 平台持久化期望状态 |
| `device_state` | `app`, `console` | 平台缓存的设备状态快照 |
| `gpio_value` | `app`, `console` | GPIO 值变化 |
| `gpio_status` | `app`, `console` | GPIO 状态同步 |
| `gpio_edge` | `app`, `console` | GPIO 边沿事件 |
| `adc_value` | `app`, `console` | ADC 值事件 |
| `signal_captured` | `app`, `console` | 波形采集结果 |
| `uart_rx` | `app`, `console` | UART 接收数据（推荐 app 用这个，不用 REST read） |
| `uart_status` | `console` 为主 | UART 状态同步 |
| `port_status` | `console` 为主 | 端口状态同步 |
| `ble_status` | `console` 为主 | BLE 总体状态 |
| `ble_pairing_enabled` | `console` 为主 | BLE 配对开启 |
| `ble_pairing_disabled` | `console` 为主 | BLE 配对关闭 |
| `ble_peers_list` | `app`, `console` | BLE peer 列表 |
| `ble_peer_connected` | `app`, `console` | BLE 新连接 |
| `ble_peer_disconnected` | `app`, `console` | BLE 断开 |
| `ble_rssi` | `app`, `console` | BLE RSSI 更新 |
| `heartbeat` | `app`, `console` | 心跳事件 |
| `error` | `app`, `console` | bridge/error 事件 |
| `cmd_result` | `app`, `console` | WS 指令执行结果 |

### 11.6 `cmd_result` 格式

成功示例：

```json
{
  "type": "cmd_result",
  "op": "gpio_get",
  "success": true,
  "data": { "value": 0 }
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

## 12. 设计边界总结

- `platform` 是公共底层：bridge、REST、WebSocket、缓存、持久化
- `console` 是硬件操作界面：显式使用 `?role=console`
- `app` 是上层业务后端：默认通过 `/ws` 接入，偏只读；允许少量业务安全命令（signal / uart_send / thread）
- 微秒级波形能力通过 `signal/tx`、`signal/rx`、`signal/exchange` 暴露，而非单独的 I2C 语义接口
