# Rose-ESP32 Platform

Python FastAPI 平台层，作为公共底层连接 ESP32 IoT Agent、上层业务后端（根目录 `app/`）与操作界面（`console/`）。

## 架构

```
platform/
├── src/
│   ├── main.py          # FastAPI 入口 + WebSocket + 事件总线
│   ├── config.py        # 硬件配置加载
│   ├── api/             # REST 路由 (GPIO, BLE, UART, Pins, System...)
│   ├── services/        # 桥接服务 (bridge_service.py)
│   ├── ws/              # WebSocket 管理器
│   ├── models/          # SQLAlchemy 模型
│   ├── db/              # 数据库初始化
│   └── bridge/          # IoT Agent TCP 协议 (symlink → ../../bridge/src)
├── tests/               # pytest 测试
├── ../requirements.txt
└── pytest.ini
```

## 快速开始

```bash
cd platform

# 安装依赖 (conda)
..\.conda\python.exe -m pip install -r ..\requirements.txt

# 启动 (Mock 模式，无需 ESP32)
..\.conda\python.exe -m uvicorn src.main:app --host 0.0.0.0 --port 8000

# 启动 (真实设备模式 — ESP32 需已连接)
# 同上，ESP32 TCP 连上 :8080 后自动同步
```

## API

详细接口文档见：[`API.md`](./API.md)

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/v1/device/status` | GET | 设备连接状态 |
| `/api/v1/hardware/config` | GET | 硬件配置 (GPIO 引脚表) |
| `/api/v1/gpio/{n}/config` | POST | 配置 GPIO 模式 |
| `/api/v1/gpio/{n}/set` | POST | 设置 GPIO 输出 |
| `/api/v1/gpio/{n}/get` | GET | 读取 GPIO |
| `/api/v1/gpio/{n}/adc` | POST | ADC 采样 |
| `/api/v1/ble/pairing/enable` | POST | 启用 BLE 配对 (返回 PIN) |
| `/api/v1/ble/pairing/disable` | POST | 禁用 BLE 配对 |
| `/api/v1/ble/peers` | GET | 已连接 BLE 设备 |
| `/api/v1/ble/scan/start` | POST | BLE RSSI 扫描 |
| `/api/v1/ble/scan/stop` | POST | 停止 RSSI 扫描 |
| `/api/v1/pins/locks` | GET/POST/DELETE | Pin 锁定管理 |
| `/api/v1/uart/{n}/send` | POST | UART 发送 |
| `/ws` | WebSocket | 多客户端实时状态推送 + 受限指令通道 |

### 资源约束

- `gpio_set` 只允许对**已绑定**且模式为 `OUTPUT` / `INPUT_OUTPUT` 的 GPIO 操作。
- 若 GPIO 当前被某个 UART 占用为 `TX/RX` 引脚，则 `gpio_set` 必须失败。
- `uart_send` / `uart_read` 只允许对**已完整配置/绑定**的 UART 操作。

## WebSocket 角色模型

`/ws` 支持多个客户端同时接入，并按角色进行权限控制：

| 角色 | 连接方式 | 能力 |
|------|----------|------|
| `app` | `/ws` 或 `/ws?role=app` | 默认角色；只读。可订阅事件、读取数据、发只读类 WS 指令 |
| `console` | `/ws?role=console` | 控制台角色；可订阅事件，并允许执行控制类 WS 指令 |

### 当前 WS 指令白名单

平台层不会把所有 REST/硬件能力都暴露到 WebSocket。只有**显式登记**的指令才允许通过 WS 调用，未登记指令一律拒绝，避免未来新增命令时出现越权。

| op | 权限类别 | 允许角色 | 说明 |
|----|----------|----------|------|
| `gpio_get` | `read` | `app`, `console` | 读取 GPIO 输入值 |
| `adc_sample` | `read` | `app`, `console` | 读取 ADC 采样值 |
| `signal_rx` | `read` | `app`, `console` | 采集微秒级波形 |
| `gpio_set` | `control` | `console` | 设置 GPIO 输出值 |
| `signal_tx` / `signal_exchange` | `control` | `console` | 输出波形或发送并采集 |
| `uart_send` / `thread_passthrough` | `control` | `console` | 发送 UART 或 Thread 数据 |

像 `gpio_config`、BLE 配对开关、UART 配置、端口绑定等敏感/改配类能力，当前**不通过 WS 暴露**；如未来需要开放，必须先在平台层显式登记权限。

## 测试

```bash
# Mock 模式
..\.conda\python.exe -m pytest tests/ -v

# 真实设备
$env:USE_REAL_DEVICE=1
..\.conda\python.exe -m pytest tests/ -v --ignore=tests/test_ws.py
```

## 事件流

```
ESP32 ──TCP──→ bridge_service ──event──→ WS Manager ──→ console (role=console)
                                       │
                                       ├──→ app backends (role=app, multi-client)
                                       └──→ API/state cache
```

WS 事件类型: `hardware_config`, `connection_change`, `expected_state`, `device_state`, `ble_status`, `ble_peers_list`, `gpio_value`, `uart_rx` 等。
