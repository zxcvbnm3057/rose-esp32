#include "iot_agent.h"
#include "esp_log.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "esp_timer.h"

static const char *TAG = "ble_manager";

// BLE peer table
ble_peer_t ble_peer_table[4] = {0};

// BLE control variables
uint8_t ble_pairing_enabled = 0;
uint32_t ble_pairing_timeout_s = 0;
uint32_t ble_pairing_start_time = 0;
uint8_t ble_rssi_scan_enabled = 0;
uint32_t ble_rssi_interval_s = 5;
uint32_t ble_rssi_last_scan_time = 0;

// BLE GAP event handler
static int ble_gap_event(struct ble_gap_event *event, void *arg);

// Forward declaration
static void ble_app_advertise(void);
static void ble_host_task(void *pvParameters);
static void ble_on_sync(void);

/**
 * BLE 初始化 - Peripheral 模式，开机自动广播
 */
void ble_manager_init(void)
{
    ESP_LOGI(TAG, "BLE Manager initializing...");

    // NimBLE port init handles controller internally (CONFIG_SOC_ESP_NIMBLE_CONTROLLER=y)
    ESP_ERROR_CHECK(nimble_port_init());
    ble_svc_gap_init();
    ble_svc_gatt_init();
    ble_svc_gap_device_name_set("ESP32-IoT-Agent");

    // Register sync callback — advertising starts after host syncs with controller
    ble_hs_cfg.sync_cb = ble_on_sync;

    // NimBLE host 就绪后自动开始广播；配对由指令控制
    nimble_port_freertos_init(ble_host_task);

    ESP_LOGI(TAG, "BLE Manager initialized (advertising ON)");
}

/**
 * NimBLE host task — MUST call nimble_port_run() for the BLE event loop.
 */
static void ble_host_task(void *pvParameters)
{
    ESP_LOGI(TAG, "NimBLE host task started, entering event loop");
    nimble_port_run();
    // nimble_port_run returns only when nimble_port_stop() is called
    nimble_port_freertos_deinit();
}

/**
 * Called when NimBLE host synchronizes with the controller.
 * This is the correct place to start advertising.
 */
static void ble_on_sync(void)
{
    ESP_LOGI(TAG, "NimBLE host synced with controller, starting advertising");
    ble_app_advertise();
}

/**
 * 开始广播（使设备可被发现）
 */
static void ble_app_advertise(void)
{
    struct ble_gap_adv_params adv_params;
    struct ble_hs_adv_fields fields;
    int rc;

    // 配置广告字段
    memset(&fields, 0, sizeof(fields));
    fields.flags = BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP;
    fields.name = (uint8_t *)"ESP32-IoT";
    fields.name_len = strlen("ESP32-IoT");
    fields.name_is_complete = 1;

    rc = ble_gap_adv_set_fields(&fields);
    if (rc != 0)
    {
        ESP_LOGE(TAG, "error setting advertisement data; rc=%d", rc);
        return;
    }

    // 配置广告参数
    memset(&adv_params, 0, sizeof(adv_params));
    adv_params.conn_mode = BLE_GAP_CONN_MODE_UND;
    adv_params.disc_mode = BLE_GAP_DISC_MODE_GEN;

    rc = ble_gap_adv_start(BLE_ADDR_PUBLIC, NULL, BLE_HS_FOREVER,
                           &adv_params, ble_gap_event, NULL);
    if (rc != 0)
    {
        ESP_LOGE(TAG, "error enabling advertisement; rc=%d", rc);
        return;
    }

    ESP_LOGI(TAG, "BLE Advertising started");
}

/**
 * GAP 事件处理器
 */
static int ble_gap_event(struct ble_gap_event *event, void *arg)
{
    switch (event->type)
    {
    case BLE_GAP_EVENT_CONNECT:
        ESP_LOGI(TAG, "BLE connect event; status=%d", event->connect.status);
        if (event->connect.status == 0)
        {
            // 连接成功
            ble_peer_t *peer = NULL;
            for (int i = 0; i < 4; i++)
            {
                if (!ble_peer_table[i].in_use)
                {
                    peer = &ble_peer_table[i];
                    // 从连接句柄获取对方地址
                    struct ble_gap_conn_desc desc;
                    ble_gap_conn_find(event->connect.conn_handle, &desc);
                    memcpy(peer->peer_mac, desc.peer_id_addr.val, 6);
                    peer->rssi = -50; // Default RSSI value
                    peer->conn_time_s = (uint32_t)(esp_timer_get_time() / 1000000);
                    peer->in_use = 1;
                    break;
                }
            }

            if (peer)
            {
                // 发送连接事件
                event_ble_peer_connected_t evt = {0};
                memcpy(evt.peer_mac, peer->peer_mac, 6);
                evt.rssi = peer->rssi;
                send_event(EVENT_BLE_PEER_CONNECTED, &evt, sizeof(evt));

                // 连接成功后禁用配对模式
                if (ble_pairing_enabled)
                {
                    ble_disable_pairing();
                }
            }
            else
            {
                ESP_LOGE(TAG, "No free peer slot");
            }
        }
        break;

    case BLE_GAP_EVENT_DISCONNECT:
        ESP_LOGI(TAG, "BLE disconnect event; reason=%d",
                 event->disconnect.reason);

        // 从表中移除设备
        for (int i = 0; i < 4; i++)
        {
            if (ble_peer_table[i].in_use)
            {
                ble_peer_table[i].in_use = 0;

                event_ble_peer_disconnected_t evt = {0};
                memcpy(evt.peer_mac, ble_peer_table[i].peer_mac, 6);
                evt.reason = event->disconnect.reason;
                send_event(EVENT_BLE_PEER_DISCONNECTED, &evt, sizeof(evt));
            }
        }

        // 重新启动广播
        ble_app_advertise();
        break;

    case BLE_GAP_EVENT_ADV_COMPLETE:
        ESP_LOGI(TAG, "advertise complete; reason=%d",
                 event->adv_complete.reason);
        break;

    default:
        break;
    }
    return 0;
}

/**
 * 启用配对模式
 */
void ble_enable_pairing(uint32_t timeout_s)
{
    ble_pairing_enabled = 1;
    ble_pairing_timeout_s = timeout_s;
    ble_pairing_start_time = (uint32_t)(esp_timer_get_time() / 1000000);

    // 生成临时 PIN
    uint8_t pin_code[6];
    for (int i = 0; i < 6; i++)
    {
        pin_code[i] = (uint8_t)((esp_timer_get_time() + i) % 10) + '0';
    }

    ESP_LOGI(TAG, "BLE pairing mode enabled, timeout=%u seconds", timeout_s);

    // 发送配对启用事件
    event_ble_pairing_enabled_t evt = {0};
    memcpy(evt.pin_code, pin_code, 6);
    evt.timeout_s = timeout_s;
    send_event(EVENT_BLE_PAIRING_ENABLED, &evt, sizeof(evt));
}

/**
 * 禁用配对模式
 */
void ble_disable_pairing(void)
{
    uint8_t reason = ble_pairing_enabled ? 2 : 0; // 2=paired, 0=other
    ble_pairing_enabled = 0;
    ble_pairing_timeout_s = 0;

    ESP_LOGI(TAG, "BLE pairing mode disabled, reason=%u", reason);

    // 发送配对禁用事件
    event_ble_pairing_disabled_t evt = {0};
    evt.reason = reason;
    send_event(EVENT_BLE_PAIRING_DISABLED, &evt, sizeof(evt));
}

/**
 * 获取已连接的蓝牙设备列表
 */
void ble_get_peers_list(ble_peer_t *peers, int *peer_count)
{
    int count = 0;
    for (int i = 0; i < 4; i++)
    {
        if (ble_peer_table[i].in_use && count < *peer_count)
        {
            memcpy(&peers[count], &ble_peer_table[i], sizeof(ble_peer_t));
            count++;
        }
    }
    *peer_count = count;

    ESP_LOGI(TAG, "Peers list: %d devices", count);
}

/**
 * 启动 RSSI 信号强度检测
 */
void ble_start_rssi_scan(uint32_t interval_s)
{
    ble_rssi_scan_enabled = 1;
    ble_rssi_interval_s = interval_s;
    ble_rssi_last_scan_time = 0;

    ESP_LOGI(TAG, "BLE RSSI scan started, interval=%u seconds", interval_s);
}

/**
 * 停止 RSSI 信号强度检测
 */
void ble_stop_rssi_scan(void)
{
    ble_rssi_scan_enabled = 0;

    ESP_LOGI(TAG, "BLE RSSI scan stopped");
}

/**
 * BLE 信号强度检测后台任务
 */
void ble_rssi_task(void *pvParameters)
{
    const TickType_t xDelay = pdMS_TO_TICKS(1000); // 每秒检查一次

    ESP_LOGI(TAG, "BLE RSSI task started");

    while (1)
    {
        vTaskDelay(xDelay);

        if (!ble_rssi_scan_enabled)
        {
            continue;
        }

        uint32_t current_time = (uint32_t)(esp_timer_get_time() / 1000000);

        // 检查是否需要发送 RSSI 更新
        if (current_time - ble_rssi_last_scan_time >= ble_rssi_interval_s)
        {
            ble_rssi_last_scan_time = current_time;

            // 遍历所有连接的设备并更新 RSSI
            for (int i = 0; i < 4; i++)
            {
                if (ble_peer_table[i].in_use)
                {
                    // 模拟 RSSI 值（-50 到 -80 dBm）
                    int8_t rssi = -60 + (i % 20);
                    ble_peer_table[i].rssi = rssi;

                    // 发送 RSSI 事件
                    event_ble_rssi_t evt = {0};
                    memcpy(evt.peer_mac, ble_peer_table[i].peer_mac, 6);
                    evt.rssi = rssi;
                    evt.timestamp_us = esp_timer_get_time();
                    send_event(EVENT_BLE_RSSI, &evt, sizeof(evt));

                    ESP_LOGI(TAG, "RSSI for peer %d: %d dBm", i, rssi);
                }
            }
        }

        // 检查配对模式超时
        if (ble_pairing_enabled && ble_pairing_timeout_s > 0)
        {
            uint32_t elapsed = current_time - ble_pairing_start_time;
            if (elapsed >= ble_pairing_timeout_s)
            {
                ble_disable_pairing();
            }
        }
    }
}
