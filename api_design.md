# 🌹 Rose-ESP32 后端 API 设计文档

> 版本: 2.0 | 日期: 2026-06-07 | 前后端分离 · 硬件无关 · 协议驱动

---

## 目录

1. [架构总览](#1-架构总览)
2. [硬件配置 JSON](#2-硬件配置-json)
3. [技术选型](#3-技术选型)
4. [REST API — 完整 Bridge 控制](#4-rest-api--完整-bridge-控制)
5. [WebSocket — 实时事件推送](#5-websocket--实时事件推送)
6. [自定义指令系统](#6-自定义指令系统)
7. [数据持久化](#7-数据持久化)

---

## 1. 架构总览

### 核心原则

- **硬件无关**: 页面展示的芯片版型、IO 布局、保留引脚、是否支持 BLE 均由 JSON 配置文件驱动，不写死任何具体芯片
- **协议驱动**: API 设计面向 Bridge 协议本身（GPIO/UART/Signal/BLE 等抽象能力），与底层 MCU 型号解耦
- **局域网内零鉴权**: 访问者视为已授权（Nginx/网关层已处理 OAuth），后端不做身份校验
- **前后端分离**: REST + WebSocket 双通道，为后续 App 拓展预留接口

```
┌─────────────────────────────────────────────────────────┐
│                     Console (React)                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐ │
│  │ 芯片视图  │ │ IO 编辑  │ │ 手动指令  │ │ 自定义指令  │ │
│  │(配置驱动) │ │          │ │          │ │            │ │
│  └──────────┘ └──────────┘ └──────────┘ └────────────┘ │
└──────────┬──────────────┬──────────────┬────────────────┘
           │ REST         │ WebSocket    │
           ▼              ▼              │
┌─────────────────────────────────────────────────────────┐
│                Platform (FastAPI + Uvicorn)              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐ │
│  │ REST API │ │   WS 推送 │ │ 指令引擎  │ │ 持久化存储  │ │
│  │ /api/v1/ │ │   /ws    │ │ 序列化执行 │ │  SQLite    │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └─────┬──────┘ │
│       └────────────┴────────────┴───────────────┘       │
│                         │                                │
│                   ┌─────┴─────┐                          │
│                   │  Bridge   │                          │
│                   │ (TCP ↔    │                          │
│                   │  ESP32)   │                          │
│                   └───────────┘                          │
└─────────────────────────────────────────────────────────┘
           │
           ▼ TCP (port 8080)
┌──────────────────┐
│  目标硬件 (MCU)   │
│  (IoT Agent)     │
└──────────────────┘
```

### 分层职责

| 层 | 路径 | 职责 |
|----|------|------|
| **Hardware Config** | `hardware_config.json` | 定义芯片版型、IO 布局、能力声明 |
| **REST API** | `/api/v1/*` | 完整 Bridge 功能：GPIO/UART/信号/BLE/端口/系统 |
| **WebSocket** | `/ws` | 实时 IO 状态推送、事件广播 |
| **Custom Cmd** | `/cmd/{slug}` | 用户预定义的指令组合，独立 URL |

---

## 2. 硬件配置 JSON

> 这是整个系统的"数据源"，前后端共享同一份配置。
> 换一块芯片？改一个 JSON 即可。

### 2.1 配置文件位置

```
platform/hardware_config.json    ← 平台层启动时加载
console/public/hardware_config.json  ← 控制台构建时内嵌（或通过 API 获取）
```

> 前端优先通过 `GET /api/v1/hardware/config` 动态获取，避免构建时写死。

### 2.2 完整 Schema

```jsonc
{
  // ====== 芯片基本信息 ======
  "chip": {
    "name": "ESP32-C6-DevKitM-1",
    "manufacturer": "Espressif",
    "family": "esp32c6"
  },

  // ====== 协议能力声明 ======
  "capabilities": {
    "gpio": true,                      // 是否支持 GPIO
    "adc": true,                       // 是否支持 ADC 采样
    "signal": true,                    // 精确信号 TX/RX/Exchange
    "uart": true,                      // 是否支持 UART
    "uart_count": 2,                   // UART 数量
    "ble": true,                       // 是否支持 BLE
    "thread": false,                   // 是否支持 Thread 透传
    "max_signal_edges": 256,           // 信号边沿上限
    "max_adc_samples": 16              // 单次 ADC 采样上限
  },

  // ====== IO 引脚定义 ======
  // 引脚只需声明所在边(side)和排序(order)，前端自动计算坐标
  "pins": [
    {
      "gpio": 0,
      "label": "GPIO0",
      "side": "top",                   // top | bottom | left | right
      "order": 0,                      // 该边上的排列序号 (从左到右/从上到下)
      "reserved": false,               // true = 保留 IO，焊盘灰色锁定
      "reserved_reason": null,
      "capabilities": {                // 此 IO 支持的模式
        "input": true,
        "output": true,
        "interrupt": true,
        "adc": false,
        "signal": false
      },
      "adc_channel": null,             // ADC 通道号
      "default_mode": "input",
      "description": "Strapping pin"
    }
    // ... 其余 IO 按 side + order 排列
  ],

  // ====== 功能分组 (决定前端 Tab 可见性) ======
  "feature_groups": [
    { "id": "gpio",   "label": "GPIO 控制",  "icon": "cpu",             "enabled": true },
    { "id": "uart",   "label": "UART 通信",  "icon": "arrow-left-right","enabled": true },
    { "id": "signal", "label": "精确信号",    "icon": "activity",        "enabled": true },
    { "id": "ble",    "label": "BLE 蓝牙",   "icon": "bluetooth",       "enabled": true },
    { "id": "thread", "label": "Thread 网络", "icon": "network",         "enabled": false }
  ]
}
```

### 2.3 前端如何计算焊盘坐标

前端遍历 `pins[]`，按 `side` 分组、按 `order` 排序后自动计算每个焊盘的 SVG 位置：

```
top   边: y = chip_y - pad_h - gap,  x = chip_x + (chip_w - 总占宽) / 2 + order * (pad_w + spacing)
bottom边: y = chip_y + chip_h + gap, x 同上
left  边: x = chip_x - pad_w - gap,  y = chip_y + (chip_h - 总占高) / 2 + order * (pad_h + spacing)
right 边: x = chip_x + chip_w + gap, y 同上
```

焊盘尺寸固定（52×36），间距固定（8px），芯片主体 480×300。这些值是前端渲染常量，不需要放进配置。

### 2.4 配置驱动逻辑

```
hardware_config.json
        │
        ├──→ 后端: 加载 capabilities
        │         ble=false → /api/v1/ble/* 返回 501
        │         thread=false → /api/v1/thread/* 返回 501
        │
        ├──→ 前端: 加载 layout + pins → 渲染芯片 SVG
        │         side="top" → 显示在芯片上方
        │         reserved=true → 焊盘灰色 + 锁定图标
        │         capabilities 决定配置面板可选模式
        │
        └──→ 前端: feature_groups → Tab 可见性
                  thread.enabled=false → 隐藏 Thread Tab
```

### 2.4 硬件配置 API

#### `GET /api/v1/hardware/config`

返回完整硬件配置 JSON。前端启动时调用此接口。

---

## 3. 技术选型

| 组件 | 技术 | 理由 |
|------|------|------|
| Web 框架 | **FastAPI** | 原生 async、自动 OpenAPI 文档、WebSocket |
| ASGI 服务器 | **Uvicorn** | 高性能 |
| 数据库 | **SQLite + aiosqlite** | 轻量零配置 |
| ORM | **SQLAlchemy 2.0 (async)** | 成熟稳定 |
| 实时通信 | **WebSocket** | 双向低延迟 |
| 序列化 | **Pydantic v2** | 类型安全 |
| 配置 | **JSON 文件** | 硬件配置即 JSON，启动加载 |

### 目录结构

```
platform/
├── hardware_config.json          # ★ 硬件配置（前后端共享）
├── app/
│   ├── __init__.py
│   ├── main.py                   # FastAPI 入口
│   ├── config.py                 # 加载 hardware_config.json
│   ├── models/
│   │   ├── __init__.py
│   │   ├── schemas.py            # Pydantic 模型
│   │   └── custom_cmd.py         # 自定义指令 ORM
│   ├── api/
│   │   ├── __init__.py
│   │   ├── router.py             # 主路由（按 capabilities 条件注册）
│   │   ├── errors.py             # 统一错误 helper + HTTPException 子类
│   │   ├── hardware.py           # 硬件配置端点
│   │   ├── gpio.py
│   │   ├── uart.py
│   │   ├── signal.py
│   │   ├── port.py
│   │   ├── ble.py
│   │   ├── system.py
│   │   └── custom_cmd.py
│   ├── ws/
│   │   ├── __init__.py
│   │   └── manager.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── bridge_service.py     # Bridge 单例
│   │   ├── device_state.py       # 状态缓存
│   │   └── cmd_executor.py       # 指令执行引擎
│   └── db/
│       ├── __init__.py
│       ├── database.py
│       └── crud.py
├── requirements.txt
└── Dockerfile
```

---

## 4. REST API — 完整 Bridge 控制

> **Base URL**: `http://{host}:8000/api/v1`  
> **无鉴权**: 局域网内自由访问  
> **文档**: `http://{host}:8000/docs` (Swagger 自动生成)

### 4.0 通用约定

#### 响应格式

所有响应（含错误）统一使用以下 JSON 结构：

```json
{
  "success": true,       // false on any error
  "data": { },           // 具体数据，错误时为 null
  "error": null,         // 错误时为人类可读描述
  "timestamp": 1717800000.123
}
```

#### HTTP 状态码

| 状态码 | 含义 | 触发场景 |
|--------|------|---------|
| **200** | 成功 | 正常 `ApiResponse` |
| **400** | 请求参数错误 | UART 发送无数据、无效 base64 |
| **403** | 资源不可用 | 保留 GPIO 引脚 (`reserved=true`) |
| **404** | 资源不存在 | GPIO 不在配置、自定义指令 slug 不存在 |
| **409** | 冲突 | 创建重复 slug |
| **422** | 校验失败 | Pydantic 参数校验不通过 |
| **501** | 硬件不支持 | `capabilities` 中功能为 false |
| **502** | Bridge 通信失败 | 设备指令返回 None/False |
| **503** | 设备未连接 | ESP32 未建立 TCP 连接 |

> 所有 4xx/5xx 错误由 `app/api/errors.py` 中的 `check_connected()` / `check_bridge_ok()` 抛出，经 `main.py` 的 `@app.exception_handler(HTTPException)` 统一格式化为上述 JSON。

#### 硬件能力检查

当硬件不支持某项功能时返回 `501 Not Implemented`，保留引脚返回 `403 Forbidden`，设备未连接返回 `503 Service Unavailable`。所有错误均遵循统一 JSON 格式。

---

### 4.1 硬件配置

#### `GET /api/v1/hardware/config`

返回完整 `hardware_config.json` 内容。

---

### 4.2 设备状态

#### `GET /api/v1/device/status`

获取连接状态 + IO 快照。

```json
{
  "connected": true,
  "uptime_seconds": 3600,
  "session_version": 42,
  "io_snapshot": {
    "gpios": [
      { "gpio": 0, "mode": "output", "mode_code": 1, "value": 1,
        "pull": "up", "pull_code": 2, "bound": true, "owner_id": 1 }
    ],
    "uarts": [
      { "uart_id": 0, "bound": true, "baudrate": 115200,
        "tx_gpio": 1, "rx_gpio": 3 }
    ],
    "ble": { "pairing_enabled": false, "scan_enabled": false, "peer_count": 0 }
  }
}
```

---

### 4.3 GPIO

| 方法 | 路径 | 请求 | 需硬件 |
|------|------|------|--------|
| `POST` | `/api/v1/gpio/{gpio}/config` | `{"mode": 1, "pull": 2, "edge": 0}` | gpio |
| `POST` | `/api/v1/gpio/{gpio}/set` | `{"value": 0\|1}` | gpio |
| `GET` | `/api/v1/gpio/{gpio}/get` | — | gpio |
| `POST` | `/api/v1/gpio/{gpio}/adc` | `{"samples": 4}` | adc |

> 校验: 请求的 `mode` 必须在该 IO 的 `capabilities` 中为 `true`

---

### 4.4 精确信号

| 方法 | 路径 | 需硬件 |
|------|------|--------|
| `POST` | `/api/v1/gpio/{gpio}/signal/tx` | signal |
| `POST` | `/api/v1/gpio/{gpio}/signal/rx` | signal |
| `POST` | `/api/v1/gpio/{gpio}/signal/exchange` | signal |

**Signal TX 请求**:
```json
{
  "signal": [
    {"level": 1, "duration_us": 100},
    {"level": 0, "duration_us": 200}
  ],
  "delay_us": 0
}
```

**Signal RX 请求**: `{"timeout_us": 1000000, "max_edges": 100}`

**Signal Exchange 请求**:
```json
{
  "tx_signal": [{"level": 1, "duration_us": 100}],
  "delay_us": 50, "rx_total_us": 500000,
  "rx_max_edges": 100, "rx_resolution_us": 1
}
```

---

### 4.5 UART

| 方法 | 路径 | 需硬件 |
|------|------|--------|
| `POST` | `/api/v1/uart/{id}/config` | uart |
| `POST` | `/api/v1/uart/{id}/send` | uart |
| `GET` | `/api/v1/uart/{id}/read?length=256&timeout_ms=3000` | uart |

**Config 请求**:
```json
{
  "baudrate": 115200, "data_bits": 8,
  "parity": 0, "stop_bits": 1,
  "tx_gpio": 1, "rx_gpio": 3
}
```

**Send 请求**: `{"data": "hello", "encoding": "utf-8"}` 或 `{"data_base64": "aGVsbG8="}`

---

### 4.6 端口/资源

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/v1/port/bind` | `{"resource_type": 0, "id": 5, "owner_id": 1}` |
| `POST` | `/api/v1/port/unbind` | `{"resource_type": 0, "id": 5}` |
| `GET` | `/api/v1/port/status?resource_type=0&id=5` | 查询占用 |

---

### 4.7 BLE

> 仅当 `capabilities.ble == true` 时可用

| 方法 | 路径 |
|------|------|
| `POST` | `/api/v1/ble/pairing/enable` |
| `POST` | `/api/v1/ble/pairing/disable` |
| `GET` | `/api/v1/ble/peers` |
| `POST` | `/api/v1/ble/scan/start` |
| `POST` | `/api/v1/ble/scan/stop` |

---

### 4.8 系统

| 方法 | 路径 | 需硬件 |
|------|------|--------|
| `POST` | `/api/v1/system/ping` | — |
| `POST` | `/api/v1/system/heartbeat` | — |
| `POST` | `/api/v1/system/sync` | — |
| `POST` | `/api/v1/system/sync/confirm` | — |
| `POST` | `/api/v1/thread/passthrough` | thread |

---

## 5. WebSocket — 实时事件推送

> **端点**: `ws://{host}:8000/ws`  
> **无鉴权**，连接即开始推送  
> **单客户端**: 同一时刻仅允许一个连接，新连接建立时旧连接被踢出

### 5.0 连接管理

- 首个客户端连接：收到 `{"type": "hardware_config", "data": {...}}`
- 第二个客户端连接时，旧连接收到 `{"type": "kicked", "reason": "new_connection"}` 后被关闭
- `ConnectionManager` 使用单 `_ws` 引用 + `asyncio.Lock` 保证原子性

### 5.1 服务端 → 客户端事件

| 事件类型 | 负载 | 说明 |
|----------|------|------|
| `hardware_config` | 完整 config JSON | 连接时发送 |
| `kicked` | `{"reason": "new_connection"}` | 被新连接踢出 |
| `device_state` | `{gpios:[], uarts:[], ble:{}}` | 全量快照 |
| `gpio_value` | `{gpio, value, timestamp_us}` | 电平变化 |
| `gpio_edge` | `{gpio, edge_type, timestamp_us}` | 边沿中断 |
| `adc_value` | `{gpio, value, voltage_mv, timestamp_us}` | ADC 结果 |
| `signal_captured` | `{gpio, edge_count, edges:[], timestamp_us}` | 信号捕获 |
| `uart_rx` | `{uart_id, data_base64}` | UART 接收 |
| `cmd_ack` | `{cmd_id, status, error_code}` | 命令确认 |
| `port_status` | `{resource_type, id, in_use, mode, value}` | 端口状态 |
| `ble_pairing_enabled` | `{pin_code, timeout_s}` | 配对启用 |
| `ble_pairing_disabled` | `{}` | 配对禁用 |
| `ble_peer_connected` | `{mac}` | 设备连接 |
| `ble_peer_disconnected` | `{mac}` | 设备断开 |
| `ble_peers_list` | `{peers:[{mac, rssi}]}` | 设备列表 |
| `ble_rssi` | `{mac, rssi}` | RSSI 更新 |
| `heartbeat` | `{connection_state}` | 心跳 |
| `error` | `{error_code, message}` | 错误 |
| `connection_change` | `{connected: bool}` | 设备连接/断开 |

### 5.2 客户端 → 服务端

前端也可通过 WS 发送指令（替代 HTTP，适合高频操作）：

```json
{ "type": "cmd", "op": "gpio_set", "gpio": 5, "value": 1 }
// 回复
{ "type": "cmd_result", "op": "gpio_set", "success": true, "data": {} }
```

---

## 6. 自定义指令系统

### 6.1 数据模型

```python
class CustomCommand:
    id: int
    slug: str                # URL 标识
    name: str                # 名称
    description: str
    icon: str                # emoji
    steps: list[CommandStep] # 有序步骤
    enabled: bool
    created_at / updated_at / last_executed_at: datetime
    execution_count: int

class CommandStep:
    step_type: str    # gpio_config|gpio_set|gpio_get|adc_sample
                      # |signal_tx|signal_rx|signal_exchange
                      # |uart_config|uart_send|uart_read
                      # |port_bind|port_unbind|delay
    config: dict      # 步骤参数
    delay_ms: int     # 步骤后延时
    on_error: str     # abort|continue
```

### 6.2 API

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/v1/cmds` | 列表 |
| `POST` | `/api/v1/cmds` | 创建 |
| `GET` | `/api/v1/cmds/{slug}` | 详情 |
| `PUT` | `/api/v1/cmds/{slug}` | 更新 |
| `DELETE` | `/api/v1/cmds/{slug}` | 删除 |
| `POST` | `/api/v1/cmds/{slug}/execute` | 执行（内部） |
| `POST` | `/cmd/{slug}` | **独立 URL**（与 execute 同处理函数） |

`/cmd/{slug}` 作为对外暴露的稳定 URL，内部与 `/api/v1/cmds/{slug}/execute` 路由到同一逻辑。

---

## 7. 数据持久化

```sql
CREATE TABLE custom_commands (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    slug            TEXT UNIQUE NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT DEFAULT '',
    icon            TEXT DEFAULT '⚡',
    steps_json      TEXT NOT NULL,
    enabled         INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    last_executed_at TEXT,
    execution_count INTEGER DEFAULT 0
);

CREATE TABLE execution_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    command_id      INTEGER NOT NULL,
    steps_results   TEXT,
    success         INTEGER,
    error_message   TEXT,
    duration_ms     INTEGER,
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (command_id) REFERENCES custom_commands(id)
);
```

---

## 附录 A: API 速查

| 分类 | 方法 | 路径 | 需硬件 |
|------|------|------|--------|
| 硬件 | `GET` | `/api/v1/hardware/config` | — |
| 设备 | `GET` | `/api/v1/device/status` | — |
| GPIO | `POST` | `/api/v1/gpio/{gpio}/config` | gpio |
| GPIO | `POST` | `/api/v1/gpio/{gpio}/set` | gpio |
| GPIO | `GET` | `/api/v1/gpio/{gpio}/get` | gpio |
| GPIO | `POST` | `/api/v1/gpio/{gpio}/adc` | adc |
| 信号 | `POST` | `/api/v1/gpio/{gpio}/signal/tx` | signal |
| 信号 | `POST` | `/api/v1/gpio/{gpio}/signal/rx` | signal |
| 信号 | `POST` | `/api/v1/gpio/{gpio}/signal/exchange` | signal |
| UART | `POST` | `/api/v1/uart/{id}/config` | uart |
| UART | `POST` | `/api/v1/uart/{id}/send` | uart |
| UART | `GET` | `/api/v1/uart/{id}/read` | uart |
| 端口 | `POST` | `/api/v1/port/bind` | — |
| 端口 | `POST` | `/api/v1/port/unbind` | — |
| 端口 | `GET` | `/api/v1/port/status` | — |
| BLE | `POST` | `/api/v1/ble/pairing/enable` | ble |
| BLE | `POST` | `/api/v1/ble/pairing/disable` | ble |
| BLE | `GET` | `/api/v1/ble/peers` | ble |
| BLE | `POST` | `/api/v1/ble/scan/start` | ble |
| BLE | `POST` | `/api/v1/ble/scan/stop` | ble |
| 系统 | `POST` | `/api/v1/system/ping` | — |
| 系统 | `POST` | `/api/v1/system/heartbeat` | — |
| 系统 | `POST` | `/api/v1/system/sync` | — |
| Thread | `POST` | `/api/v1/thread/passthrough` | thread |
| 自定义 | `GET\|POST` | `/api/v1/cmds` | — |
| 自定义 | `GET\|PUT\|DELETE` | `/api/v1/cmds/{slug}` | — |
| 自定义 | `POST` | `/api/v1/cmds/{slug}/execute` | — |
| 外部URL | `POST` | `/cmd/{slug}` | — |
| WebSocket | — | `ws://host:8000/ws` | — |
