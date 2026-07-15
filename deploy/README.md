# Rose Platform 与 Home Assistant 部署

## 网络边界

PVE 主编排中的 `esp32-platform` 同时加入两个 Docker 网络，但不使用宿主机 `ports:`：

- `192.168.137.80`（`standard_network`/macvlan）
  - `8000/tcp`：只允许 HA Server `192.168.137.200` 访问 API 与 app WebSocket
  - `8080/tcp`：只允许 `ROSE_DEVICE_ALLOWLIST` 中的 ESP32 地址访问
- `172.18.0.80`（`db_network`）
  - Console 和 Console API 只允许 bastion `172.18.0.254` 访问

HA 自身的登录或反向代理认证不需要配置到 Rose。HA 集成从 HA Server 主动访问 `http://192.168.137.80:8000`。

部署前应将 `ROSE_DEVICE_ALLOWLIST` 从示例的 `192.168.137.0/24` 收紧到 ESP32 的静态地址，例如 `192.168.137.51/32`。

ESP32 固件通过未提交的 `include/config.h` 获取目标地址。复制 `include/config.TEMPLATE.h` 后保留你的 Wi-Fi 配置，并设置：

```c
#define SERVER_IP_STR "192.168.137.80"
#define SERVER_PORT_NUM 8080
```

然后重新构建并烧录固件。`include/config.h` 包含 Wi-Fi 密码，已被 `.gitignore` 排除，不要提交。

## 部署 ESP32 Platform

唯一部署编排是 PVE 工作区中的 `docker-compose.yml`。在 PVE Docker 主机对应目录执行：

```bash
docker compose config --quiet
docker compose up -d --build esp32-platform
```

不要在 Rose 仓库中维护第二份 compose。`/mnt/nfs/esp32-platform:/data` 保存 platform 自己的 SQLite 数据，但它不属于 Home Assistant 备份；如需备份，由 PVE/NFS 层独立处理。ESP32 的 NVS 配对与芯片配置同样不进入 Home Assistant 备份。

验证 HA 可访问的 API：

```bash
curl http://192.168.137.80:8000/api/v1/device/status
```

从其他 LAN 主机访问应返回 `403`。

## 通过 Bastion 访问 Console

在客户端建立 SSH 本地转发；`2278` 是现有 bastion 的宿主机 SSH 端口：

```bash
ssh -N -L 8000:rose-platform:8000 -p 2278 developer@<PVE_HOST>
```

浏览器打开：

```text
http://127.0.0.1:8000/console/
```

不要为 Console 添加 SWAG 路由或公开端口。

## 安装 Home Assistant 集成

### HACS 自定义仓库

1. 将源码推送到公开仓库 `https://github.com/zxcvbnm3057/rose-esp32` 的默认分支。
2. HACS -> Integrations -> Custom repositories。
3. 添加仓库 URL，类型选择 `Integration`。
4. 安装 `Rose` 并重启 Home Assistant。

HACS 会直接安装默认分支中 `custom_components/rose` 的源码，不需要 tag、GitHub Release、ZIP 安装包或 GitHub Actions。

### 手动安装

集成的唯一源码位于仓库的 `custom_components/rose`。手动安装时，将该目录放到 HA 的以下位置：

```text
/config/custom_components/rose
```

HA OS 可通过 Samba share、Studio Code Server 或 SSH add-on 写入 `/config`。然后重启 HA。

## 配置 Home Assistant

无需编辑 `configuration.yaml`：

1. Settings -> Devices & services -> Add integration。
2. 搜索 `Rose`。
3. 填写 HA 可访问的 Platform 地址，默认 `http://192.168.137.80:8000`。
4. 添加完成后打开 Rose 集成的 Configure 菜单。
5. 在 UI 中添加、编辑或删除 TCL 空调与 UART 灯。

设备的稳定标识只在新增时填写，创建后不能修改；名称、GPIO、首次使用默认温度、重复参数和 UART 指令都可以继续编辑。这样可保持实体 ID、历史和恢复状态稳定。

第一版实体：

- `binary_sensor.rose_platform_esp32_connection`
- `climate.bedroom_ac`（实体 ID 由 HA 名称规则生成）
- 客厅灯与卧室灯 `light` 实体
- platform 上报的每个已知 BLE MAC 对应一个 `device_tracker`

空调和 UART 灯都是单向控制，HA 显示的是最后一次成功发送的乐观状态。

## 持久化与备份边界

Home Assistant 自身保存并随 HA 备份的内容：

- Rose Platform URL
- UI 中添加的空调和 UART 灯配置
- HA 设备/实体注册表
- 空调完整乐观状态：开关、最后模式、目标温度、风速、扫风、省电、健康、强力、面板灯、定时和辅热
- UART 灯最后一次成功发送的开关状态

不进入 Home Assistant 备份的内容：

- `esp32-platform` 的 `/mnt/nfs/esp32-platform:/data` 数据
- platform SQLite、BLE 显示名称、Pin/UART 配置
- ESP32 NVS 中的 BLE bond、芯片配置和固件配置

这些数据由 PVE/NFS 与 ESP32 自己管理；Rose HA 集成不会复制或备份它们。

## BLE 在场与用户绑定

BLE 配对和已知设备记忆由 ESP32 负责，名称由 platform/console 管理。HA 配置不填写 MAC；集成会从 platform 的设备名称、范围快照和 WebSocket 事件动态发现全部已知设备。

每个设备在 HA 中表现为 `device_tracker`：

- 进入范围：`home`
- 离开范围：`not_home`
- Rose platform 或 ESP32 断线：实体变为 unavailable，不误判为离家
- RSSI：保存在实体属性 `rssi`

在 HA 的 Settings -> People 中，把属于家庭用户的 tracker 绑定到对应 `person`。未绑定到 `person` 的 tracker 只是“未绑定用户设备”；业务上可以把它归类为客人或陌生用户，但 Rose 集成本身不会推断设备持有者身份。

进入和离开还会触发 `rose_ble_presence` 事件，字段包括 `name`、`mac`、`home` 和 `rssi`。例如监听所有已知设备进入范围：

```yaml
trigger:
  - platform: event
    event_type: rose_ble_presence
    event_data:
      home: true
action:
  - action: notify.notify
    data:
      message: "检测到已知 BLE 设备进入范围：{{ trigger.event.data.name }}"
```

如果只希望处理客人/陌生用户，请在 HA 中维护相应 tracker 实体列表或 Group，并在自动化条件中排除已绑定家庭用户的 tracker。

扩展 TCL 功能通过服务调用：

```yaml
action: rose.send_tcl
data:
  climate: bedroom
  turbo: true
  light: false
  timer_minutes: 30
  aux_heat: false
```
