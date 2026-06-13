# 🌹 Rose-ESP32 前端设计文档

> 版本: 2.0 | 日期: 2026-06-07 | 配置驱动 · 硬件无关 · 功能优先

---

## 目录

1. [核心原则](#1-核心原则)
2. [技术选型](#2-技术选型)
3. [配置驱动架构](#3-配置驱动架构)
4. [页面与路由](#4-页面与路由)
5. [芯片可视化](#5-芯片可视化)
6. [IO 编辑交互](#6-io-编辑交互)
7. [手动指令面板](#7-手动指令面板)
8. [自定义指令管理](#8-自定义指令管理)
9. [实时数据流](#9-实时数据流)
10. [目录结构](#10-目录结构)

---

## 1. 核心原则

- **配置驱动**: 芯片版型、IO 布局、保留引脚、BLE 支持全部来自 `GET /api/v1/hardware/config`，零硬编码
- **硬件无关**: 换芯片只改 JSON，不改代码
- **功能完整**: 覆盖所有 Bridge 命令，支持手动发射和自定义指令
- **实现从简**: 不需要花哨动效，功能跑通优先。SVG 自绘芯片图 + Tailwind 样式即可

---

## 2. 技术选型

| 组件 | 技术 | 理由 |
|------|------|------|
| 框架 | **React 18** + TypeScript | 类型安全 |
| 构建 | **Vite 5** | 快 |
| 样式 | **Tailwind CSS** | 原子化，出活快 |
| 芯片图 | **SVG（自绘）** | 精准控制，无额外依赖 |
| 状态管理 | **Zustand** | 2KB，够用 |
| 数据请求 | **TanStack Query v5** | 缓存 + 自动刷新 |
| WebSocket | **原生 WebSocket + 自封装 Hook** | 零依赖 |
| 路由 | **React Router v6** | SPA 标准 |
| 表单 | **React Hook Form + Zod** | 类型安全校验 |

### 无鉴权

局域网内不校验身份，直接调用 API / 连接 WebSocket。

---

## 3. 配置驱动架构

### 3.1 启动流程

```
App 启动
  │
  ├─→ GET /api/v1/hardware/config
  │     获取芯片布局、IO 列表、能力声明
  │
  ├─→ 连接 WebSocket ws://host:8000/ws
  │     收到 hardware_config + device_state
  │
  └─→ 根据 config 渲染 UI
        ├── pins[] → 芯片 SVG 焊盘
        ├── capabilities → 隐藏不支持的功能 Tab
        ├── feature_groups → Tab 列表
        └── reserved pins → 灰色锁定
```

### 3.2 配置如何驱动 UI

| 配置字段 | 驱动 UI |
|----------|---------|
| `layout.chip_body` | SVG 芯片主体矩形位置/大小 |
| `layout.chip_label` | 芯片名称文字 |
| `pins[].x/y` | 焊盘在 SVG 中的坐标 |
| `pins[].side` | 焊盘在哪一边（顶部一排、底部一排…） |
| `pins[].reserved` | 焊盘灰色 + 锁定图标 + 禁止点击编辑 |
| `pins[].capabilities` | 配置面板中哪些模式按钮可选 |
| `pins[].adc_channel` | ADC 采样时使用的通道号 |
| `capabilities.ble` | BLE Tab 是否显示 |
| `capabilities.thread` | Thread Tab 是否显示 |
| `feature_groups` | 底部导航 Tab 列表 |

---

## 4. 页面与路由

### 4.1 SPA 路由

```
/                     → 芯片视图（默认首页）
/commands             → 手动指令面板
/custom-commands      → 自定义指令列表
/custom-commands/:slug/edit → 指令编辑器
/logs                 → 执行日志
```

### 4.2 布局结构

```
┌──────────────────────────────────────────────┐
│  Header                                       │
│  🌹 Rose-ESP32        ● 已连接  运行 01:23   │
├──────────────────────────────────────────────┤
│                                               │
│            主内容区 (React Router)              │
│                                               │
├──────────────────────────────────────────────┤
│  Footer (Tab 导航，由 feature_groups 决定)     │
│  [芯片视图] [GPIO] [UART] [信号] [BLE]  ...  │
└──────────────────────────────────────────────┘
```

---

## 5. 芯片可视化

### 5.1 SVG 结构与坐标计算

焊盘坐标完全由代码根据 `side` + `order` 自动计算，不写在 JSON 里：

```tsx
// 渲染常量 (前端代码内硬编码，不放进 JSON)
const PAD_W = 52, PAD_H = 36;        // 焊盘尺寸
const PAD_GAP = 8;                    // 焊盘间距
const CHIP_X = 160, CHIP_Y = 100;     // 芯片主体左上角
const CHIP_W = 480, CHIP_H = 300;     // 芯片主体尺寸
const MARGIN = 12;                    // 焊盘离芯片边缘距离

function computePadPositions(pins: PinConfig[]) {
  const grouped = { top: [], bottom: [], left: [], right: [] };
  for (const p of pins) grouped[p.side].push(p);
  for (const side of Object.keys(grouped)) {
    grouped[side].sort((a, b) => a.order - b.order);
  }

  const positions: Record<number, {x: number, y: number}> = {};

  // top 边: 水平等距排列
  const topPins = grouped.top;
  const topTotalW = topPins.length * PAD_W + (topPins.length - 1) * PAD_GAP;
  topPins.forEach((p, i) => {
    positions[p.gpio] = {
      x: CHIP_X + (CHIP_W - topTotalW) / 2 + i * (PAD_W + PAD_GAP),
      y: CHIP_Y - PAD_H - MARGIN,
    };
  });

  // bottom 边: 同上，在芯片下方
  const botPins = grouped.bottom;
  const botTotalW = botPins.length * PAD_W + (botPins.length - 1) * PAD_GAP;
  botPins.forEach((p, i) => {
    positions[p.gpio] = {
      x: CHIP_X + (CHIP_W - botTotalW) / 2 + i * (PAD_W + PAD_GAP),
      y: CHIP_Y + CHIP_H + MARGIN,
    };
  });

  // left 边: 垂直等距排列
  const leftPins = grouped.left;
  const leftTotalH = leftPins.length * PAD_H + (leftPins.length - 1) * PAD_GAP;
  leftPins.forEach((p, i) => {
    positions[p.gpio] = {
      x: CHIP_X - PAD_W - MARGIN,
      y: CHIP_Y + (CHIP_H - leftTotalH) / 2 + i * (PAD_H + PAD_GAP),
    };
  });

  // right 边: 同上，在芯片右侧
  const rightPins = grouped.right;
  const rightTotalH = rightPins.length * PAD_H + (rightPins.length - 1) * PAD_GAP;
  rightPins.forEach((p, i) => {
    positions[p.gpio] = {
      x: CHIP_X + CHIP_W + MARGIN,
      y: CHIP_Y + (CHIP_H - rightTotalH) / 2 + i * (PAD_H + PAD_GAP),
    };
  });

  return positions;
}

function ChipView() {
  const config = useHardwareConfig();
  const positions = useMemo(() => computePadPositions(config.pins), [config.pins]);

  return (
    <svg width={800} height={520}>
      {/* 芯片主体 */}
      <rect x={CHIP_X} y={CHIP_Y} width={CHIP_W} height={CHIP_H}
            rx={12} fill="#1e293b" stroke="#334155" />
      <text x={CHIP_X + CHIP_W/2} y={CHIP_Y + CHIP_H/2}
            textAnchor="middle" fill="#94a3b8" fontSize={24}>
        {config.chip.name}
      </text>

      {/* IO 焊盘 */}
      {config.pins.map(pin => {
        const pos = positions[pin.gpio];
        return <PinPad key={pin.gpio} x={pos.x} y={pos.y}
                       config={pin} state={ioState[pin.gpio]} />;
      })}
    </svg>
  );
}
```

### 5.2 焊盘颜色规则

| IO 状态 | 外框色 | 填充色 | 显示 |
|---------|--------|--------|------|
| 保留 (reserved) | `#374151` 灰 | `#111827` 深色 | GPIO 编号 + 🔒 |
| 未配置 | `#4b5563` | `#1f2937` | GPIO 编号 |
| INPUT | `#3b82f6` 蓝 | `#1e3a5f` | 编号 + "IN" |
| OUTPUT 高 | `#22c55e` 绿 | `#14532d` | 编号 + "OUT" + ● |
| OUTPUT 低 | `#6b7280` | `#374151` | 编号 + "OUT" + ○ |
| INTERRUPT | `#eab308` 黄 | `#422006` | 编号 + "INT" |
| ADC | `#a855f7` 紫 | `#3b0764` | 编号 + ADC值 |
| SIGNAL | `#ef4444` 红 | `#450a0a` | 编号 + "SIG" |

### 5.3 焊盘组件 (PinPad)

```tsx
function PinPad({ x, y, config, state, onClick, onContextMenu }) {
  const isReserved = config.reserved;
  const colors = getPinColors(state?.mode, state?.value, isReserved);

  return (
    <g transform={`translate(${x}, ${y})`}
       onClick={() => !isReserved && onClick(config.gpio)}
       onContextMenu={(e) => { e.preventDefault(); onContextMenu(config.gpio); }}
       style={{ cursor: isReserved ? 'not-allowed' : 'pointer' }}>
      <rect width={PAD_W} height={PAD_H} rx={6}
            stroke={colors.border} fill={colors.fill}
            strokeWidth={state?.bound ? 2.5 : 1.5} />
      <text x={PAD_W/2} y={14} textAnchor="middle"
            fill={colors.text} fontSize={11} fontWeight="bold">
        {config.label}
      </text>
      <text x={PAD_W/2} y={28} textAnchor="middle"
            fill={colors.text} fontSize={9}>
        {getModeLabel(state?.mode)}
      </text>
      {isReserved && (
        <text x={PAD_W - 8} y={10} fontSize={8}>🔒</text>
      )}
    </g>
  );
}
```

---

## 6. IO 编辑交互

### 6.1 点击焊盘 → 配置面板

点击非保留 IO 焊盘，右侧弹出配置面板（或移动端底部 Sheet）：

```
┌─────────────────────────────────┐
│  GPIO 2 配置                    │
├─────────────────────────────────┤
│  当前: ADC · 采样值 2048        │
│                                  │
│  模式: (仅显示 capabilities 允许的)│
│  [INPUT] [OUTPUT] [INT] [ADC*]  │
│  [SIGNAL]                        │
│                                  │
│  ── 根据模式显示子选项 ──         │
│  OUTPUT: 电平 [高] [低]          │
│  INT:    边沿 [上升] [下降] [双] │
│  ADC:    采样次数 [4]            │
│                                  │
│  上下拉: [无] [下拉] [上拉]      │
│                                  │
│  端口: 已绑定(owner:1) [解绑]    │
│                                  │
│  [应用配置]                      │
└─────────────────────────────────┘
```

### 6.2 模式选择由 capabilities 限制

```tsx
// 只渲染 config.capabilities 中为 true 的模式
const availableModes = [
  { value: 0, label: 'INPUT',      enabled: config.capabilities.input },
  { value: 1, label: 'OUTPUT',     enabled: config.capabilities.output },
  { value: 2, label: 'INTERRUPT',  enabled: config.capabilities.interrupt },
  { value: 3, label: 'ADC',        enabled: config.capabilities.adc },
  { value: 4, label: 'SIGNAL',     enabled: config.capabilities.signal },
].filter(m => m.enabled);
```

### 6.3 右键菜单

```
┌──────────────────┐
│ 📥 设为 INPUT     │
│ 📤 设为 OUTPUT    │
│ 📊 设为 ADC       │
│ ⚠️  设为 INT       │
│ 📶 设为 SIGNAL    │
│ ──────────────── │
│ 🔓 强制解绑       │
└──────────────────┘
```

---

## 7. 手动指令面板

### 7.1 布局

```
┌──────────────────────────────────────────┐
│  手动指令发射                              │
├────────────────┬─────────────────────────┤
│  指令分类       │  参数表单                │
│                │                          │
│  📌 GPIO       │  命令: gpio_config       │
│   · config     │  GPIO: [5]              │
│   · set        │  Mode: [OUTPUT ▼]       │
│   · get        │  Pull: [UP ▼]           │
│   · adc_sample │                          │
│                │  [⚡ 发送]               │
│  📶 信号        │                          │
│   · signal_tx  │  ── 历史 ──              │
│   · signal_rx  │  10:30 gpio_set(5,1) ✓  │
│   · exchange   │  10:29 adc(2) → 2048    │
│                │                          │
│  📡 UART       │                          │
│   · config     │                          │
│   · send       │                          │
│   · read       │                          │
│                │                          │
│  🔌 端口        │                          │
│  📶 BLE        │                          │
│  ⚙️  系统       │                          │
└────────────────┴─────────────────────────┘
```

左侧指令树也由 `feature_groups` 控制可见性。

### 7.2 指令 → 表单映射

每种指令有对应的 Zod Schema，根据 Schema 动态渲染表单字段：

```typescript
const commandSchemas = {
  gpio_config: z.object({
    gpio: z.number().min(0).max(23),
    mode: z.number().min(0).max(4),
    pull: z.number().min(0).max(2).default(0),
    edge: z.number().min(0).max(3).default(0),
  }),
  gpio_set: z.object({
    gpio: z.number(),
    value: z.union([z.literal(0), z.literal(1)]),
  }),
  // ...
};
```

---

## 8. 自定义指令管理

### 8.1 指令列表

```
┌──────────────────────────────────────────────┐
│  自定义指令                        [+ 新建]   │
├──────────────────────────────────────────────┤
│  ┌────────────────────────────────────────┐  │
│  │ 🔌 切换继电器1          执行 42 次     │  │
│  │ 翻转 GPIO5 3 次 · 3 步骤              │  │
│  │ 外部URL: /cmd/toggle-relay-1          │  │
│  │                  [▶执行] [✎编辑] [✕]  │  │
│  └────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────┐  │
│  │ 📊 传感器读取           执行 17 次     │  │
│  │ ADC2→GPIO5→UART0 · 3 步骤             │  │
│  │ 外部URL: /cmd/sensor-read-all         │  │
│  │                  [▶执行] [✎编辑] [✕]  │  │
│  └────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
```

### 8.2 指令编辑器

```
┌──────────────────────────────────────────────┐
│  编辑自定义指令                       [保存]  │
├──────────────────────────────────────────────┤
│  Slug: [sensor-read-all________]             │
│  名称: [批量传感器读取__________]             │
│  图标: [📊]                                  │
│                                              │
│  ── 步骤列表 ────────────────────────────    │
│  ┌─ 步骤 1 ────────────────────── [✕] [↓] ┐ │
│  │ 类型: [ADC Sample ▼]                    │ │
│  │ GPIO: [2]  采样次数: [4]                │ │
│  │ 延时: [100] ms  错误: [中止 ▼]          │ │
│  └─────────────────────────────────────────┘ │
│  ┌─ 步骤 2 ────────────────────── [✕] [↑] ┐ │
│  │ 类型: [GPIO Get ▼]                      │ │
│  │ GPIO: [5]  延时: [50] ms                │ │
│  └─────────────────────────────────────────┘ │
│  [+ 添加步骤]                                │
│                                              │
│  ── JSON 预览 ──────────────────────────    │
│  { "steps": [...] }                          │
└──────────────────────────────────────────────┘
```

---

## 9. 实时数据流

### 9.1 WebSocket Hook

```typescript
function useDeviceWebSocket() {
  const store = useDeviceStore();
  const queryClient = useQueryClient();

  useEffect(() => {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${location.host}/ws`);

    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      switch (msg.type) {
        case 'hardware_config':
          store.setHardwareConfig(msg.data);
          break;
        case 'device_state':
          store.hydrateState(msg.data);
          break;
        case 'gpio_value':
          store.updatePin(msg.gpio, { value: msg.value });
          break;
        case 'adc_value':
          store.updatePin(msg.gpio, { adc_value: msg.value, adc_voltage_mv: msg.voltage_mv });
          break;
        case 'connection_change':
          store.setConnected(msg.connected);
          break;
        // ... 其他事件同理
      }
    };

    return () => ws.close();
  }, []);
}
```

### 9.2 Zustand Store

```typescript
interface DeviceStore {
  // 硬件配置
  hardwareConfig: HardwareConfig | null;
  setHardwareConfig: (c: HardwareConfig) => void;

  // 连接状态
  connected: boolean;
  setConnected: (v: boolean) => void;

  // IO 状态 (gpio → PinState)
  pinStates: Record<number, PinState>;
  updatePin: (gpio: number, partial: Partial<PinState>) => void;
  hydrateState: (snapshot: DeviceSnapshot) => void;

  // 指令历史
  history: CommandLog[];
  addHistory: (log: CommandLog) => void;
}
```

### 9.3 React Query (REST 降级)

```typescript
function useDeviceStatus() {
  return useQuery({
    queryKey: ['device', 'status'],
    queryFn: () => api.get('/api/v1/device/status'),
    refetchInterval: 10000,  // WS 断开时 10s 轮询兜底
  });
}
```

---

## 10. 目录结构

```
console/
├── public/
│   └── favicon.svg
├── src/
│   ├── main.tsx
│   ├── App.tsx                        # 路由 + 布局
│   ├── index.css                      # Tailwind
│   │
│   ├── components/
│   │   ├── layout/
│   │   │   ├── Header.tsx
│   │   │   └── TabBar.tsx             # 底部导航 (由 feature_groups 驱动)
│   │   │
│   │   ├── chip/
│   │   │   ├── ChipView.tsx           # SVG 主容器
│   │   │   ├── PinPad.tsx             # 单个焊盘
│   │   │   ├── PinContextMenu.tsx      # 右键菜单
│   │   │   └── pinColors.ts           # 颜色映射
│   │   │
│   │   ├── panels/
│   │   │   ├── PinConfigSheet.tsx      # IO 配置面板
│   │   │   └── UartConfigPanel.tsx
│   │   │
│   │   ├── commands/
│   │   │   ├── CommandPanel.tsx        # 手动指令面板
│   │   │   ├── CommandForm.tsx         # 动态参数表单
│   │   │   └── CommandHistory.tsx
│   │   │
│   │   ├── custom-cmds/
│   │   │   ├── CustomCmdList.tsx
│   │   │   ├── CustomCmdEditor.tsx
│   │   │   └── StepEditor.tsx
│   │   │
│   │   └── ui/                         # 通用 UI
│   │       ├── Modal.tsx
│   │       ├── Drawer.tsx
│   │       └── Select.tsx
│   │
│   ├── hooks/
│   │   ├── useHardwareConfig.ts        # 硬件配置
│   │   ├── useWebSocket.ts            # WS 连接
│   │   ├── useGpio.ts
│   │   ├── useUart.ts
│   │   ├── useSignal.ts
│   │   ├── useBle.ts
│   │   └── useCustomCmd.ts
│   │
│   ├── stores/
│   │   └── deviceStore.ts             # Zustand
│   │
│   ├── services/
│   │   └── api.ts                     # fetch 封装
│   │
│   ├── schemas/
│   │   └── commands.ts                # Zod 指令校验
│   │
│   └── types/
│       ├── hardware.ts                # HardwareConfig 类型
│       ├── device.ts                  # PinState 类型
│       └── events.ts                  # WS 事件类型
│
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts
└── tailwind.config.ts
```

---

## 附录 A: 组件树

```
<App>
  <Header />                      ← 连接状态 + 芯片名称

  <Routes>
    <Route path="/" element={<ChipView />}>
      <ChipView>
        <svg>
          <ChipBody />            ← 芯片主体矩形
          <ChipLabel />           ← 芯片名称
          {pins.map(p => <PinPad />)}  ← 配置驱动
        </svg>
        <PinConfigSheet />        ← 选中 IO 时弹出
        <PinContextMenu />        ← 右键菜单
      </ChipView>
    </Route>

    <Route path="/commands" element={<CommandPanel />} />
    <Route path="/custom-commands" element={<CustomCmdList />} />
    <Route path="/custom-commands/:slug/edit" element={<CustomCmdEditor />} />
    <Route path="/logs" element={<ExecutionLog />} />
  </Routes>

  <TabBar />                      ← feature_groups 驱动
</App>
```
