# Rose-ESP32 Console

React + TypeScript + Vite + Tailwind 控制台界面，可视化管控 ESP32 IoT Agent。

## 架构

```
console/
├── src/
│   ├── App.tsx              # 主布局
│   ├── main.tsx             # 入口
│   ├── components/
│   │   ├── chip/            # 芯片引脚视图 (ChipView, PinPad)
│   │   ├── panels/          # 功能面板 (BlePanel, StatusPanel, PinConfigSheet)
│   │   └── custom-cmds/     # 自定义指令编辑器
│   ├── hooks/
│   │   └── useWebSocket.ts  # WebSocket 连接 + 事件分发
│   ├── stores/
│   │   └── deviceStore.ts   # Zustand 全局状态
│   ├── services/
│   │   └── api.ts           # REST API 封装
│   └── types/
│       └── index.ts         # TypeScript 类型定义
├── index.html
├── package.json
├── vite.config.ts
└── tailwind.config.js
```

## 快速开始

```bash
cd console
npm install
npx vite --host
```

打开 `http://localhost:5173`，后端需运行在 `localhost:8000`。

## 与 Platform 的连接方式

Console 通过两种通道与 `platform` 交互：

- **REST API**：执行配置、控制、查询等操作
- **WebSocket**：订阅实时事件与状态变化

WebSocket 连接地址为：

```text
ws://127.0.0.1:8000/ws?role=console
```

说明：

- `platform` 的 `/ws` 支持**多客户端同时接入**
- 默认角色是 `app`（业务后端，只读）
- `console` 必须显式带 `?role=console`，才允许执行控制类 WS 指令
- 当前控制台的多数硬件操作仍通过 REST API 发起；WS 主要承担实时状态分发与少量受限指令

## 功能面板

| 面板 | 说明 |
|------|------|
| **芯片视图** | ESP32 引脚布局，点击配置模式 (INPUT/OUTPUT/ADC/SIGNAL) |
| **BLE 面板** | 配对开关 + PIN 码显示 + 已连接设备 RSSI |
| **设备状态** | 实时 GPIO 状态、UART 绑定 |
| **自定义指令** | 用户自定义命令 CRUD + 执行 |

## 状态管理 (Zustand)

```
useDeviceStore
├── hardwareConfig    # 硬件引脚配置
├── pinStates         # GPIO 实时状态
├── uartStates        # UART 绑定状态
├── bleState          # BLE 配对/扫描/peer数
├── blePeers[]        # 已连接 BLE 设备列表
├── connected         # ESP32 连接状态
└── history[]         # 操作日志
```

## BLE 事件 (WebSocket)

| 事件 | Store 操作 |
|------|-----------|
| `ble_status` | `setBleState` |
| `ble_pairing_enabled` | `setBleState({pairingEnabled:true})` |
| `ble_peers_list` | `setBlePeers` |
| `ble_peer_connected` | `upsertBlePeer` |
| `ble_peer_disconnected` | `removeBlePeer` |
| `ble_rssi` | `upsertBlePeer` (更新 RSSI) |

## 构建

```bash
npx vite build     # → dist/
npx vite preview   # 预览生产构建
```
