# IoT 远程硬件代理（ESP32+Server）设计文档

## 1. 目标与职责分离

- ESP32：
  - 作为 TCP 客户端，连接 Server 服务端（container 内）
  - 负责命令转发与事件上报（无业务栈，仅硬件抽象）
  - GPIO/UART/ADC/RMT/BLE 统一资源管理，冲突检测（`resource_mutex`）
  - 事件驱动：收命令入队、dispatch、执行、send_queue 顺序上报
  - 心跳、断线重连、资源保留（断线时逻辑保留状态）
  - BLE Peripheral + 配对开关 + 连接/断开/RSSI 上报
  - 精确 IO 电平信号：`CMD_GPIO_SIGNAL_TX`、`CMD_GPIO_SIGNAL_RX`、`CMD_GPIO_SIGNAL_EXCHANGE`

- Server：
  - TCP 服务端接收事件并下发命令
  - 上层协议（Matter/CoAP/业务）
  - 实现重试/超时、报文解析、命令组合

---

## 2. 组件结构（ESP32 实现）

- `tcp_client_task`（网络层，客户端 socket，自动重连）
- `command_dispatcher_task`（协议解析、命令路由）
- `send_task`（事件报文发送队列）
- `heartbeat_task`（10s 心跳，30s 失联重连）
- `uart_rx_task`（UART 接收转事件）
- `gpio_signal_tx_task`（RMT TX/Exchange）
- `gpio_signal_rx_task`（GPIO 中断 RX）
- `ble_manager` + `ble_rssi_task`（BLE 周期 RSSI 与配对管理）
- `gpio_signal_init/get_signal_tx_queue/get_signal_rx_queue`
- 全局资源表：`gpio_table[31]`, `uart_table[2]`, `thread_table[16]`

---

## 3. 协议帧（实际代码）

- 头部由 `msg_frame_t` 定义（`version|type|length|cmd_id|crc`）
- `type`:
  - `0x01 CMD`
  - `0x02 ACK`（通过 `EVENT_CMD_ACK` 返回）
  - `0x03 EVENT`（各类上报）
  - `0x04 ERROR`（兼容错误上报）

### 3.1 消息扩展与同步命令格式

- `cmd_id` 仍用于帧级别传输匹配。
- `correlation_id` 为业务级别关联键，用于跨命令、ACK、下游结果、SYN 的业务关联。
- `correlation_id` 不随同一业务逻辑的重传变化。

#### 新增命令

- `CMD_SYNC_REQUEST`：重连后上位机请求设备当前状态快照。
- `CMD_SYN`：上位机对已经收到的 ACK / 结果发送同步确认。

#### 新增事件

- `EVENT_SYNC_RESPONSE`：设备返回状态快照与待确认项清单。
- `EVENT_THREAD_RESPONSE`：下游设备透传结果事件，携带 `correlation_id`。

### 3.2 基本结构示例

#### Frame Header

```c
typedef struct {
    uint8_t version;
    uint8_t type;
    uint16_t length;
    uint16_t cmd_id;
    uint16_t crc;
    uint8_t payload[0];
} msg_frame_t;
```

#### 关联字段

```c
typedef struct {
    uint32_t correlation_id;
} correlation_header_t;
```

#### `CMD_SYN` payload

```c
typedef struct {
    uint32_t correlation_id;
    uint8_t stage; // 0=command ack sync, 1=result sync
} cmd_syn_t;
```

#### `EVENT_CMD_ACK` payload

```c
typedef struct {
    uint16_t cmd_id;
    uint8_t status;
    uint8_t error_code;
    uint32_t correlation_id;
} event_cmd_ack_t;
```

#### `CMD_THREAD_PASSTHROUGH`

```c
typedef struct {
    uint16_t device_id;
    uint16_t payload_len;
    uint32_t correlation_id;
    uint8_t payload[0];
} cmd_thread_passthrough_t;
```

#### `EVENT_THREAD_RESPONSE`

```c
typedef struct {
    uint16_t device_id;
    uint16_t payload_len;
    uint32_t correlation_id;
    int64_t timestamp_us;
    uint8_t payload[0];
} event_thread_response_t;
```

#### `EVENT_SYNC_RESPONSE` 结构

```c
typedef struct {
    uint32_t session_version;
    uint16_t resource_count;
    uint16_t pending_count;
    // followed by resource snapshot entries + pending result entries
} event_sync_response_t;
```

`event_sync_response_t` 可携带多种状态项：

- 端口绑定状态（`EVENT_PORT_STATUS` 形式或简化表）
- BLE 断连/连接历史事件
- 下游透传/路由结果及其 `correlation_id`

### 3.3 同步与重传格式规则

- `CMD_SYNC_REQUEST` 只需一个固定头，无需携带 `correlation_id`。
- `EVENT_SYNC_RESPONSE` 返回当前快照，并包含“应保留重传”的三类数据：
  - BLE 断连事件
  - 下游透传/路由结果
  - 端口绑定状态
- `CMD_SYN` 用于两类确认：
  - stage 0：确认设备已收到命令并已返回 `EVENT_CMD_ACK`
  - stage 1：确认已收到 `EVENT_THREAD_RESPONSE` 等下游结果

---

## 4. 事件/命令流程

1. `tcp_client_task` 接收 TCP 数据，解析成 `msg_frame_t *`，入 `cmd_queue`
2. `command_dispatcher_task` 取命令，`handle_command()`
3. 资源检查、GPIO/UART/ADC/BLE 操作
4. 生成 `EVENT_CMD_ACK` / 各类事件，放入 `send_queue`
5. `send_task` 串行发送到容器

---

## 5. GPIO与RMT精确信号

- `CMD_GPIO_CONFIG`:
  - gpio, mode, pull, edge
  - 支持类型: `INPUT`, `OUTPUT`, `INTERRUPT`, `ADC`, `SIGNAL`

- `CMD_GPIO_SET`:
  - `gpio`, `value`
  - 仅在 `OUTPUT` 模式下有效

- `CMD_GPIO_GET`:
  - 读 `gpio` 电平，发 `EVENT_GPIO_VALUE`

- `CMD_ADC_SAMPLE`:
  - `gpio`, `samples`，调用 `adc_read_sample`，发 `EVENT_ADC_VALUE`

- `CMD_GPIO_SIGNAL_TX`:
  - `gpio`, `signal_len`, `delay_us`, 后续 tx payload (`signal_len` 个 items: 1 byte level + 4 byte duration_us)
  - 路径：`command_dispatcher`->`gpio_signal_tx_queue`->`gpio_signal_tx_task`
  - `gpio_signal_tx_task` 在实际执行时动态申请 RMT TX 通道并发送（`clk_div=80`）
  - 发送完成后：`delay_us` -> send `EVENT_CMD_ACK`

- `CMD_GPIO_SIGNAL_RX`:
  - `gpio`, `timeout_us`, `max_edges`
  - 持续 `timeout_us` 微秒（直接使用 `esp_timer_get_time()` 比较），开启 GPIO ISR `signal_capture_isr`
  - 采集 `edge` info：`level`, `duration_us`（差值）
  - 该命令为 GPIO ISR 捕获路径，不占用 RMT RX 资源（`rx_channel` 字段保留为 -1 仅用于队列项布局统一）
  - 结束后发 `EVENT_GPIO_SIGNAL_CAPTURED` + `EVENT_CMD_ACK`

- `CMD_GPIO_SIGNAL_EXCHANGE`（关键）:
  - `gpio`, `tx_len`, `delay_us`, `rx_total_us`, `rx_max_edges`, `rx_resolution_us`
  - `payload` 同 `CMD_GPIO_SIGNAL_TX` 以下 `tx_len` 项
  - 发送队列项中 `do_rx=1`
  - `gpio_signal_tx_task` 发送 TX，等待 `delay_us`
  - 如果 `do_rx`，在任务执行时动态申请 RMT RX 通道并持续 `rx_total_us`（基于 `esp_timer_get_time()`）
  - 通过 `rmt_get_ringbuf_handle` 读取 `rmt_item32_t`，最多 `rx_max_edges`
  - `rx_resolution_us` 当前用于 RX filter threshold（对短脉冲抑制有实际影响）
  - 结果构建 `EVENT_GPIO_SIGNAL_CAPTURED` 包含：
    - `gpio`, `edge_count`, `timestamp_us`, 紧随 `edge_count` 条 `signal_edge_t`
  - 完成后发 `EVENT_CMD_ACK`

- `EVENT_GPIO_SIGNAL_CAPTURED` 数据结构
  - `gpio`, `edge_count`, `timestamp_us`, 各边沿元组 `level` + `duration_us`

---

## 6. BLE 业务

- `ble_manager_init`:
  - NimBLE Peripheral 模式
  - 名称 `ESP32-IoT-Agent`，广播名 `ESP32-IoT`
  - 开机自动广播

- `CMD_BLE_ENABLE_PAIRING`:
  - `timeout_s`
  - 记录 `ble_pairing_enabled` 和 `ble_pairing_timeout_s`
  - 生成随机 PIN（6位ASCII数字）
  - 发送 `EVENT_BLE_PAIRING_ENABLED`

- `CMD_BLE_DISABLE_PAIRING`:
  - 禁用并发送 `EVENT_BLE_PAIRING_DISABLED`

- `CMD_BLE_GET_PEERS`:
  - 返回 `EVENT_BLE_PEERS_LIST`，每个 Peer: 6B mac + 1B rssi

- `CMD_BLE_START_SCAN`:
  - 启用 `ble_rssi_scan_enabled`，周期 `interval_s`
  - `ble_rssi_task` 每秒检查并按间隔发 `EVENT_BLE_RSSI`

- GAP 事件：
  - `CONNECT` -> `EVENT_BLE_PEER_CONNECTED`, 连接成功后 `ble_disable_pairing`
  - `DISCONNECT` -> `EVENT_BLE_PEER_DISCONNECTED`, 重新广播

---

## 7. 资源/端口与其他命令

### UART（事件驱动接收模型）

- `CMD_UART_CONFIG`:
  - 配置并安装 UART driver，同时创建并绑定 UART 事件队列
  - 从该时刻开始，`uart_rx_task` 按事件队列消费 `UART_DATA` 并立即上报 `EVENT_UART_RX`
- `CMD_UART_SEND`:
  - 仅负责写入发送数据并返回 `EVENT_CMD_ACK`
- `CMD_UART_READ`:
  - 轮询读取命令（50ms 超时），返回 `EVENT_UART_RX`
  - 保留用于兼容场景；推荐上位机在 `configure` 成功后直接消费 `EVENT_UART_RX`（监听队列/回调）
- `CMD_PORT_UNBIND` 对 UART:
  - 释放资源同时删除 UART driver，并清空事件队列句柄

- `CMD_PORT_BIND`:
  - 资源类型 `0=gpio`, `1=uart`
  - 写 `gpio_table`/`uart_table` 状态

- `CMD_PORT_UNBIND`:
  - 释放资源，设置 `in_use=0`, `owner=0`，重置相关状态
  - GPIO：重置 mode/value/last_ts
  - UART：重置 tx_pin/rx_pin/baudrate

- `CMD_PORT_STATUS`:
  - 返回 `EVENT_PORT_STATUS` 包含当前模式/占用/值
  - 与 `CMD_PORT_UNBIND` 共用 `cmd_port_op_t` 结构体

### 补充命令

- `CMD_PING` (`0xFF`):
  - 无 payload，设备回复 `EVENT_CMD_ACK`（status=0）
  - 用于连接保活检测

- `CMD_HEARTBEAT` (`0xFE`):
  - 上位机主动发送心跳，payload 包含 `timestamp`
  - 设备回显 `EVENT_HEARTBEAT` 携带当前 `connection_state`
  - 与设备自发的 10s 周期心跳互补

### 补充事件

- `EVENT_GPIO_EDGE` (`0x22`):
  - 当 GPIO 配置为 `INTERRUPT` 模式时，通过 `gpio_isr_handler` 自动上报
  - payload: `gpio`, `edge_type`, `timestamp_us`

---

## 8. 运行与网络

- `tcp_client_task`：
  - 目标 IP: `SERVER_IP`, PORT: `SERVER_PORT`
  - 断线后指数退避重连（从 1s 开始）
  - 接收 `msg_frame_t` 并入 `cmd_queue`

- `heartbeat_task`：
  - 每 10s 发送 `EVENT_HEARTBEAT`
  - 检测 30s 未收到命令/心跳触发重连

- `send_task`：
  - `send_queue` 串行输出，通过当前 socket

---

## 9. 断连/重连与状态同步方案

### 9.1 目标

- 上位机重启或长期掉线后，重新连接时能准确恢复设备当前状态。
- 重要命令与结果不丢失，设备端持久化缓存未确认项。
- 端口绑定类指令不依赖简单重传去重，而是通过状态查询比对后按需重发。
- 透传/路由类指令使用 `cmd/ack/syn` 三步流，并使用 `correlation_id` 维护业务关联性。

### 9.2 连接恢复流程

1. 设备 `tcp_client_task` 自动重连到 Server。
2. 连接建立后，设备保留当前 `gpio_table`、`uart_table`、`thread_table` 等资源状态，不做自动撤销。
3. 上位机收到连接后，第一步应发送专用状态同步请求 `CMD_SYNC_REQUEST`。
4. 设备以 `CMD_SYNC_RESPONSE` 返回当前状态快照，并附带应当保留重传的三类数据：
   - BLE 断连/连接事件
   - 下游设备透传/路由结果
   - 端口绑定状态
5. 上位机对返回快照进行核对：
   - 已绑定的端口不必重发绑定指令
   - 绑定指令只在“状态未生效”时重发
   - 其他命令（电平设置、透传、路由）可按 `correlation_id` 去重后安全重发
6. 上位机收到未确认的结果事件后，发送 `CMD_SYN`，设备收到后清除对应缓存。

### 9.3 重要命令与结果可靠性

#### `cmd/ack/syn` 三步确认

- `CMD_*`：上位机发送命令，`msg_frame_t.cmd_id` 用于帧级别传输和重传匹配。
- `EVENT_CMD_ACK`：设备收到命令并开始执行后返回，表示本机已接受命令。
- `CMD_SYN`：上位机收到 ACK 后再发送同步确认，设备在收到 `CMD_SYN` 后释放对应的缓存。

对于大多数非绑定指令，这个流程保证了：

- 如果 `CMD` 未到达，设备不会 ACK，主机可重试；
- 如果 `CMD` 到达但 `ACK` 丢失，主机重发 `CMD`，设备可根据 `correlation_id` 或旧记录直接回复 `ACK`；
- 如果 `ACK` 到达但 `SYN` 丢失，设备仍保留记录，等待重连后主机继续确认。

#### `correlation_id` 的作用

- `cmd_id` 保留为传输级帧 ID。
- `correlation_id` 作为业务级别关联键，用于将：
  - 原始命令
  - `EVENT_CMD_ACK`
  - 下游结果事件（如 `EVENT_THREAD_RESPONSE`）
  - 最终 `SYN`
  关联到同一个逻辑请求。
- 透传/路由指令（Thread/Matter）建议在 payload 内携带 `correlation_id`，并在所有相关事件中继承该值。

### 9.4 Thread/Matter 透传指令处理

- `CMD_THREAD_PASSTHROUGH` 仍使用正常的命令接收逻辑：
  1. 上位机发送命令带 `correlation_id`。
  2. 设备本地接收并校验目标资源在线后返回 `EVENT_CMD_ACK`，ACK payload 中保留同一 `correlation_id`。
  3. 上位机收到该 `EVENT_CMD_ACK` 后，返回一次 `CMD_SYN`，表明命令已安全接收。
  4. 设备转发命令到下游设备，并等待下游返回结果。
- 下游结果到达后，设备发送 `EVENT_THREAD_RESPONSE` 并携带同一 `correlation_id`。
- 上位机收到 `EVENT_THREAD_RESPONSE` 后，再发送第二次 `CMD_SYN`，以告知设备该下游结果已被安全接收。
- 设备仅在收到第二次 `CMD_SYN` 后，才清除对应 `correlation_id` 的下游设备结果缓存。

### 9.5 端口绑定类指令的同步原则

- 端口绑定类指令无需靠 `cmd_id` 去重。
- 设备应当维护端口状态表，并在重连时通过 `CMD_PORT_STATUS` 或状态快照直接告诉上位机当前结果。
- 上位机应先查询再判断是否需要重发绑定/解绑命令，避免重复申请或误解绑。
- 绑定指令的防重放和幂等，更多依赖于资源表一致性与状态查询而不是单纯重传机制。

### 9.6 设备端缓存与持久化

- 设备端应缓存两类未确认项：
  - 已接收但未 `SYN` 确认的命令 `correlation_id`
  - 已生成但未收到 `SYN` 的透传/下游结果
- 这些缓存项要持久化到 NVS，避免设备重启后丢失“已执行但未确认”的状态。
- 设备保留缓存直到收到对应 `SYN`，避免在丢包/重连场景中误删。
- 由于当前 `cmd_id` 16bit 对业务负载足够，且掉线后不会继续收到大量命令，`cmd_id` 回绕问题可以忽略。但业务相关关联仍宜用 `correlation_id`。

### 9.7 断线重连后的事件重传

- 设备应保留以下三类重要事件并支持重传，而不是在断线时直接丢弃：
  - BLE 断连/连接事件
  - 下游设备透传/路由结果
  - 端口绑定状态变化
- 普通状态心跳和采样类短桢事件可以继续采用“失联丢弃”策略，但以上三类关键结果必须放到 pending 重传队列，直到上位机确认。

### 9.8 连接初始化同步序列

- 连接恢复时，设备可以向上位机报告“待确认项清单”，包括：
  - 当前资源状态快照
  - 未确认的 `correlation_id` 列表
  - 未确认的透传/下游结果
  - 应当保留重传的 BLE 断连事件、下游结果和端口绑定数据
- 上位机收到后，逐条比对并恢复确认流程。
- 这使得“上位机重启后先查询状态，再判断是否要重发”的原则得到保障。

---

## 11. 结构体清单 (关键)

见 `include/iot_agent.h` 的真实定义。

- `cmd_gpio_signal_exchange_t` 结构字段已经按代码实现：
  - `gpio`, `tx_len`, `delay_us`, `rx_total_us`, `rx_max_edges`, `rx_resolution_us`

- `event_gpio_signal_captured_t`：
  - `gpio`, `edge_count`, `timestamp_us`

- `event_ble_*` 系列通过 `ble_manager.c` 实现。

---

## 12. 说明

- 单个 GPIO 信号/ADC/串口状态由 `gpio_table` / `uart_table` 管理，使用 `resource_mutex` 互斥。
- 所有事件通过 `send_event()` 转成 `send_queue`，避免直接在 ISR/高优先任务中 socket 操作。
- RMT RX 以时间窗口 (`rx_total_us`) 为主，边沿上限由 `rx_max_edges` 控制。
- RMT 资源仅在命令真正执行时申请，命令排队阶段不占用通道，避免不必要占用。
- `CMD_GPIO_SIGNAL_EXCHANGE` 由单一 `gpio_signal_tx_task` 串行执行；连续请求默认排队，不会因排队阶段提前占用导致资源耗尽。
- 设计与实现已融合，且满足“无需记录新增、全量覆盖当前功能”要求。

### 实现说明（与设计文档对齐）

- `correlation_id` 的 sync 保护仅对 `CMD_THREAD_PASSTHROUGH` 生效（唯一显式传递 correlation_id 的命令）。GPIO/端口/UART/BLE 命令直接发送 `EVENT_CMD_ACK` 不缓存，遵循 §9.5 的端口绑定类指令同步原则。
- `event_thread_response_t` 在代码中去掉了设计文档中的 `_ex` 后缀，结构体字段与 `event_thread_response_ex_t` 一致。
- `event_ble_peers_list_t` 线格式为 1B `peer_count` + N×(6B MAC + 1B RSSI)，数据手动拼接在结构体尾部。
