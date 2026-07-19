# Rose ESP32 Platform

Rose 将 ESP32-C6 作为通用 GPIO、ADC、UART、BLE 与微秒级信号执行器，并通过局域网连接 Home Assistant。

## 组成

- `src/`、`include/`：ESP32 固件
- `platform/`：设备 TCP bridge 与通用 FastAPI
- `console/`：Platform 管理控制台
- `custom_components/rose/`：Rose Home Assistant 自定义集成的唯一源码和 HACS 标准目录
- `Dockerfile`：合并 Platform 与 Console 的 `esp32-platform` 镜像

## Home Assistant 与 HACS

Rose 集成提供：

- UI 配置和设备管理，无需编辑 `configuration.yaml`
- TCL 红外空调 `climate`
- UART 灯 `light`
- 已知 BLE 设备动态 `device_tracker`
- 空调和灯的乐观状态恢复

### 通过 HACS 安装

1. HACS -> Integrations -> Custom repositories。
2. 仓库填写 `https://github.com/zxcvbnm3057/rose-esp32`。
3. 类型选择 `Integration`。
4. 安装 `Rose` 并重启 Home Assistant。
5. Settings -> Devices & services -> Add integration -> Rose。
6. 填写 `http://192.168.137.80:8000`，然后在 Rose 集成条目中添加“空调”或“UART 灯”子条目。

Rose 最低要求 Home Assistant 2025.3。空调和 UART 灯使用 Config Subentry 原生管理，可在集成条目中分别添加、编辑和删除。

[在 HACS 中打开此仓库](https://my.home-assistant.io/redirect/hacs_repository/?owner=zxcvbnm3057&repository=rose-esp32&category=integration)

HACS 直接从仓库默认分支的 `custom_components/rose` 安装源码，不需要 GitHub Release、ZIP 安装包或 GitHub Actions。更新默认分支后，在 HACS 中重新下载 Rose 即可获取最新源码。

空调 Dashboard 可使用 Rose 自带的固定遥控器卡：[deploy/home-assistant/rose-climate-remote-card.yaml](deploy/home-assistant/rose-climate-remote-card.yaml)。卡片不依赖 Mushroom，只需配置主 `climate` 实体；使用步骤见 [deploy/README.md](deploy/README.md#空调遥控器卡)。

## 部署

Docker 部署以 PVE 工作区的主 `docker-compose.yml` 为唯一编排。完整网络、白名单、SSH Console、HA 配置和备份边界说明见 [deploy/README.md](deploy/README.md)。

## 开发验证

```powershell
.\.conda\python.exe -m json.tool hacs.json
.\.conda\python.exe -m json.tool custom_components\rose\manifest.json
.\.conda\python.exe -m compileall -q custom_components\rose
.\.conda\python.exe -m pytest tests\test_ha_tcl_protocol.py platform\tests\test_ble.py platform\tests\test_security.py -q
npm --prefix console run build
```
