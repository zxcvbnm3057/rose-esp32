# Rose-ESP32 Backend

Python FastAPI 后端，桥接 ESP32 IoT Agent 与 Web 前端。

## 架构

```
backend/
├── app/
│   ├── main.py          # FastAPI 入口 + WebSocket + 事件总线
│   ├── config.py        # 硬件配置加载
│   ├── api/             # REST 路由 (GPIO, BLE, UART, Pins, System...)
│   ├── services/        # 桥接服务 (bridge_service.py)
│   ├── ws/              # WebSocket 管理器
│   ├── models/          # SQLAlchemy 模型
│   ├── db/              # 数据库初始化
│   └── bridge/          # IoT Agent TCP 协议 (symlink → ../../bridge/src)
├── tests/               # pytest 测试
├── requirements.txt
└── pytest.ini
```

## 快速开始

```bash
cd backend

# 安装依赖 (conda)
.\.conda\python.exe -m pip install -r requirements.txt

# 启动 (Mock 模式，无需 ESP32)
.\.conda\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 启动 (真实设备模式 — ESP32 需已连接)
# 同上，ESP32 TCP 连上 :8080 后自动同步
```

## API

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
| `/ws` | WebSocket | 实时状态推送 |

## 测试

```bash
# Mock 模式
.\.conda\python.exe -m pytest tests/ -v

# 真实设备
$env:USE_REAL_DEVICE=1
.\.conda\python.exe -m pytest tests/ -v --ignore=tests/test_ws.py
```

## 事件流

```
ESP32 ──TCP──→ bridge_service ──event──→ WS Manager ──→ 前端
                                       └──→ API cache
```

WS 事件类型: `hardware_config`, `device_state`, `ble_status`, `ble_peers_list`, `gpio_value`, `uart_rx` 等。
