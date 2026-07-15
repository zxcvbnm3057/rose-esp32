# Rose ESP32 Platform

Rose 将 ESP32-C6 作为通用 GPIO、ADC、UART、BLE 与微秒级信号执行器，并通过局域网连接 Home Assistant。

## 组成

- `src/`、`include/`：ESP32 固件
- `platform/`：设备 TCP bridge 与通用 FastAPI
- `console/`：Platform 管理控制台
- `homeassistant/component/`：Rose Home Assistant 自定义集成的唯一源码
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
6. 填写 `http://192.168.137.80:8000`，然后在 Configure 菜单中添加设备。

[在 HACS 中打开此仓库](https://my.home-assistant.io/redirect/hacs_repository/?owner=zxcvbnm3057&repository=rose-esp32&category=integration)

HACS 使用 GitHub Release 中固定名称的 `rose-home-assistant.zip`。维护者推送与 manifest 版本一致的 tag（例如 `v0.1.0`）后，GitHub Actions 会直接从 `homeassistant/component` 创建 Release 和安装包。

## 部署

Docker 部署以 PVE 工作区的主 `docker-compose.yml` 为唯一编排。完整网络、白名单、SSH Console、HA 配置和备份边界说明见 [deploy/README.md](deploy/README.md)。

## 开发验证

```powershell
.\.conda\python.exe -m pytest tests\test_ha_tcl_protocol.py platform\tests\test_ble.py platform\tests\test_security.py -q
npm --prefix console run build
```
