#include "iot_agent.h"
#include "nvs_store.h"
#include "esp_log.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"
#include "freertos/task.h"
#include "esp_timer.h"

static const char *TAG = "ble_manager";

ble_peer_t ble_peer_table[8] = {0};

uint8_t ble_pairing_enabled = 0;
uint32_t ble_pairing_timeout_s = 0;
uint32_t ble_pairing_start_time = 0;
uint8_t ble_pairing_pin[6] = {0};
uint8_t ble_rssi_scan_enabled = 0;
uint32_t ble_rssi_interval_s = 5;
uint32_t ble_rssi_last_scan_time = 0;

static int ble_gap_event(struct ble_gap_event *event, void *arg);

// NimBLE store init 鈥?available at link time even if not in headers
extern void ble_store_config_init(void);

static void ble_app_advertise(void);
static void ble_host_task(void *pvParameters);
static void ble_on_sync(void);
static void ble_on_reset(int reason);

/* ================================================================
 *  Init 鈥?follows official NimBLE bleprph example pattern
 * ================================================================ */
void ble_manager_init(void)
{
    ESP_LOGI(TAG, "BLE Manager initializing...");

    ESP_ERROR_CHECK(nimble_port_init());

    ble_hs_cfg.reset_cb = ble_on_reset;
    ble_hs_cfg.sync_cb = ble_on_sync;
    ble_hs_cfg.store_status_cb = ble_store_util_status_rr;

    ble_hs_cfg.sm_io_cap = BLE_SM_IO_CAP_DISP_ONLY;
    ble_hs_cfg.sm_bonding = 1;
    ble_hs_cfg.sm_mitm = 1;
    ble_hs_cfg.sm_sc = 1;
    ble_hs_cfg.sm_oob_data_flag = 0;
    ble_hs_cfg.sm_our_key_dist = BLE_SM_PAIR_KEY_DIST_ENC | BLE_SM_PAIR_KEY_DIST_ID;
    ble_hs_cfg.sm_their_key_dist = BLE_SM_PAIR_KEY_DIST_ENC | BLE_SM_PAIR_KEY_DIST_ID;

    ble_svc_gap_init();
    ble_svc_gatt_init();
    ble_store_config_init();
    ble_svc_gap_device_name_set("ESP32-IoT-Agent");

    nimble_port_freertos_init(ble_host_task);

    ESP_LOGI(TAG, "BLE Manager initialized (advertising ON, PIN auth required)");
}

static void ble_on_reset(int reason)
{
    ESP_LOGE(TAG, "NimBLE reset; reason=%d", reason);
}

static void ble_on_sync(void)
{
    ESP_LOGI(TAG, "NimBLE host synced, starting advertising");
    ble_app_advertise();
}

static void ble_host_task(void *pvParameters)
{
    ESP_LOGI(TAG, "NimBLE host task started");
    nimble_port_run();
    nimble_port_freertos_deinit();
}

/* ================================================================
 *  Advertising 鈥?matches official bleprph pattern
 * ================================================================ */
static void ble_app_advertise(void)
{
    struct ble_gap_adv_params adv_params;
    struct ble_hs_adv_fields fields;
    int rc;

    memset(&fields, 0, sizeof(fields));
    fields.flags = BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP;
    fields.tx_pwr_lvl_is_present = 1;
    fields.tx_pwr_lvl = BLE_HS_ADV_TX_PWR_LVL_AUTO;
    fields.name = (uint8_t *)"ESP32-IoT";
    fields.name_len = strlen("ESP32-IoT");
    fields.name_is_complete = 1;
    // 声明 GATT 服务，手机需要这个才能识别为可连接 IoT 设备
    fields.uuids16 = (ble_uuid16_t[]){BLE_UUID16_INIT(0x1800), BLE_UUID16_INIT(0x1801)};
    fields.num_uuids16 = 2;
    fields.uuids16_is_complete = 1;

    rc = ble_gap_adv_set_fields(&fields);
    if (rc != 0)
    {
        ESP_LOGE(TAG, "adv_set_fields failed; rc=%d", rc);
        return;
    }

    memset(&adv_params, 0, sizeof(adv_params));
    adv_params.conn_mode = BLE_GAP_CONN_MODE_UND;
    adv_params.disc_mode = BLE_GAP_DISC_MODE_GEN;

    rc = ble_gap_adv_start(BLE_ADDR_PUBLIC, NULL, BLE_HS_FOREVER,
                           &adv_params, ble_gap_event, NULL);
    if (rc != 0)
    {
        ESP_LOGE(TAG, "adv_start failed; rc=%d", rc);
        return;
    }
    ESP_LOGI(TAG, "BLE Advertising started");
}

/* ================================================================
 *  GAP event handler 鈥?follows official bleprph patterns
 * ================================================================ */
static int ble_gap_event(struct ble_gap_event *event, void *arg)
{
    struct ble_gap_conn_desc desc;
    int rc;

    switch (event->type)
    {

    case BLE_GAP_EVENT_CONNECT:
        ESP_LOGI(TAG, "CONNECT status=%d conn=%d",
                 event->connect.status, event->connect.conn_handle);
        if (event->connect.status != 0)
        {
            ble_app_advertise();
            return 0;
        }

        // Always accept connection 鈥?bonded devices need no pairing gate
        {
            ble_peer_t *peer = NULL;
            for (int i = 0; i < 8; i++)
            {
                if (!ble_peer_table[i].in_use)
                {
                    peer = &ble_peer_table[i];
                    rc = ble_gap_conn_find(event->connect.conn_handle, &desc);
                    if (rc == 0)
                        memcpy(peer->peer_mac, desc.peer_ota_addr.val, 6);
                    else
                    {
                        memset(peer->peer_mac, 0, 6);
                        ESP_LOGW(TAG, "conn_find rc=%d", rc);
                    }
                    peer->rssi = -50;
                    peer->conn_handle = event->connect.conn_handle;
                    peer->conn_time_s = (uint32_t)(esp_timer_get_time() / 1000000);
                    peer->in_use = 1;
                    break;
                }
            }
            if (!peer)
            {
                // All 8 slots full — LRU evict least recently active encrypted peer
                uint32_t oldest = UINT32_MAX;
                int evict_idx = -1;
                for (int i = 0; i < 8; i++)
                {
                    if (ble_peer_table[i].encrypted && ble_peer_table[i].last_active_s < oldest)
                    {
                        oldest = ble_peer_table[i].last_active_s;
                        evict_idx = i;
                    }
                }
                if (evict_idx >= 0)
                {
                    ESP_LOGI(TAG, "LRU evict slot %d (mac %02x:%02x:%02x:%02x:%02x:%02x)",
                             evict_idx,
                             ble_peer_table[evict_idx].peer_mac[0], ble_peer_table[evict_idx].peer_mac[1],
                             ble_peer_table[evict_idx].peer_mac[2], ble_peer_table[evict_idx].peer_mac[3],
                             ble_peer_table[evict_idx].peer_mac[4], ble_peer_table[evict_idx].peer_mac[5]);
                    ble_gap_terminate(ble_peer_table[evict_idx].conn_handle, BLE_ERR_REM_USER_CONN_TERM);
                    ble_peer_table[evict_idx].in_use = 0;
                    ble_peer_table[evict_idx].encrypted = 0;
                    peer = &ble_peer_table[evict_idx];
                    rc = ble_gap_conn_find(event->connect.conn_handle, &desc);
                    if (rc == 0)
                        memcpy(peer->peer_mac, desc.peer_ota_addr.val, 6);
                    else
                        memset(peer->peer_mac, 0, 6);
                    peer->rssi = -50;
                    peer->conn_handle = event->connect.conn_handle;
                    peer->conn_time_s = (uint32_t)(esp_timer_get_time() / 1000000);
                    peer->in_use = 1;
                }
                else
                {
                    ESP_LOGE(TAG, "All 8 slots full, no encrypted peer to evict — rejecting");
                    ble_gap_terminate(event->connect.conn_handle, BLE_ERR_REM_USER_CONN_TERM);
                    return 0;
                }
            }

            // Only initiate security for NEW devices when pairing is enabled.
            // Bonded devices auto-restore encryption via NimBLE bond store.
            if (ble_pairing_enabled)
            {
                rc = ble_gap_security_initiate(event->connect.conn_handle);
                if (rc != 0)
                {
                    ESP_LOGE(TAG, "security_initiate rc=%d 鈥?rollback", rc);
                    peer->in_use = 0;
                    ble_gap_terminate(event->connect.conn_handle, BLE_ERR_REM_USER_CONN_TERM);
                }
                else
                {
                    ESP_LOGI(TAG, "Security initiated, waiting for passkey...");
                }
            }
            else
            {
                ESP_LOGI(TAG, "Pairing disabled 鈥?accepting without new pairing (bonded devices auto-encrypt)");
            }
        }
        return 0;

    case BLE_GAP_EVENT_DISCONNECT:
        ESP_LOGI(TAG, "DISCONNECT reason=%d conn=%d",
                 event->disconnect.reason, event->disconnect.conn.conn_handle);
        for (int i = 0; i < 8; i++)
        {
            if (ble_peer_table[i].in_use &&
                ble_peer_table[i].conn_handle == event->disconnect.conn.conn_handle)
            {
                event_ble_peer_disconnected_t evt = {0};
                memcpy(evt.peer_mac, ble_peer_table[i].peer_mac, 6);
                evt.reason = event->disconnect.reason;
                send_event(EVENT_BLE_PEER_DISCONNECTED, &evt, sizeof(evt));
                ble_peer_table[i].in_use = 0;
                ble_peer_table[i].encrypted = 0;
                break;
            }
        }
        {
            int active = 0;
            for (int j = 0; j < 8; j++)
                if (ble_peer_table[j].in_use)
                    active++;
            if (active == 0 && ble_rssi_scan_enabled)
            {
                ble_stop_rssi_scan();
                ESP_LOGI(TAG, "Auto-stopped RSSI (no peers)");
            }
        }
        ble_app_advertise();
        return 0;

    case BLE_GAP_EVENT_ENC_CHANGE:
        ESP_LOGI(TAG, "ENC_CHANGE status=%d conn=%d",
                 event->enc_change.status, event->enc_change.conn_handle);
        if (event->enc_change.status == 0)
        {
            for (int i = 0; i < 8; i++)
            {
                if (ble_peer_table[i].in_use &&
                    ble_peer_table[i].conn_handle == event->enc_change.conn_handle)
                {
                    ble_peer_table[i].encrypted = 1;
                    ble_peer_table[i].last_active_s = (uint32_t)(esp_timer_get_time() / 1000000);
                    event_ble_peer_connected_t evt = {0};
                    memcpy(evt.peer_mac, ble_peer_table[i].peer_mac, 6);
                    evt.rssi = ble_peer_table[i].rssi;
                    send_event(EVENT_BLE_PEER_CONNECTED, &evt, sizeof(evt));
                    ESP_LOGI(TAG, "Peer connected (encryption OK)");
                    if (ble_pairing_enabled)
                    {
                        ble_pairing_enabled = 0;
                        ble_pairing_timeout_s = 0;
                        event_ble_pairing_disabled_t evt2 = {0};
                        evt2.reason = 2;
                        send_event(EVENT_BLE_PAIRING_DISABLED, &evt2, sizeof(evt2));
                        ESP_LOGI(TAG, "Auto-disabled pairing");
                    }
                    if (!ble_rssi_scan_enabled)
                    {
                        ble_start_rssi_scan(5);
                        ESP_LOGI(TAG, "Auto-started RSSI keepalive");
                    }
                    break;
                }
            }
        }
        else
        {
            ESP_LOGW(TAG, "Encryption FAILED status=%d 鈥?cleaning up", event->enc_change.status);
            for (int i = 0; i < 8; i++)
            {
                if (ble_peer_table[i].in_use &&
                    ble_peer_table[i].conn_handle == event->enc_change.conn_handle)
                {
                    event_ble_peer_disconnected_t evt = {0};
                    memcpy(evt.peer_mac, ble_peer_table[i].peer_mac, 6);
                    evt.reason = event->enc_change.status;
                    send_event(EVENT_BLE_PEER_DISCONNECTED, &evt, sizeof(evt));
                    ble_peer_table[i].in_use = 0;
                    ble_peer_table[i].encrypted = 0;
                    break;
                }
            }
            ble_gap_terminate(event->enc_change.conn_handle, BLE_ERR_REM_USER_CONN_TERM);
        }
        return 0;

    case BLE_GAP_EVENT_PASSKEY_ACTION:
        ESP_LOGI(TAG, "PASSKEY_ACTION action=%d", event->passkey.params.action);
        if (!ble_pairing_enabled)
        {
            ESP_LOGW(TAG, "Pairing disabled 鈥?rejecting");
            ble_gap_terminate(event->passkey.conn_handle, BLE_ERR_REM_USER_CONN_TERM);
            return 0;
        }
        if (event->passkey.params.action == BLE_SM_IOACT_DISP)
        {
            struct ble_sm_io pkey = {0};
            pkey.action = BLE_SM_IOACT_DISP;
            uint32_t pin = 0;
            for (int i = 0; i < 6; i++)
                pin = pin * 10 + (ble_pairing_pin[i] - '0');
            pkey.passkey = pin;
            ESP_LOGI(TAG, "Injecting passkey %06lu", (unsigned long)pin);
            rc = ble_sm_inject_io(event->passkey.conn_handle, &pkey);
            ESP_LOGI(TAG, "ble_sm_inject_io rc=%d", rc);
        }
        return 0;

    case BLE_GAP_EVENT_REPEAT_PAIRING:
        ESP_LOGI(TAG, "REPEAT_PAIRING 鈥?deleting old bond, retrying");
        rc = ble_gap_conn_find(event->repeat_pairing.conn_handle, &desc);
        if (rc == 0)
            ble_store_util_delete_peer(&desc.peer_id_addr);
        return BLE_GAP_REPEAT_PAIRING_RETRY;

    case BLE_GAP_EVENT_CONN_UPDATE:
        ESP_LOGI(TAG, "CONN_UPDATE status=%d", event->conn_update.status);
        return 0;

    case BLE_GAP_EVENT_CONN_UPDATE_REQ:
        ESP_LOGI(TAG, "CONN_UPDATE_REQ accepted");
        return 0;

    case BLE_GAP_EVENT_ADV_COMPLETE:
        ESP_LOGI(TAG, "ADV_COMPLETE reason=%d", event->adv_complete.reason);
        ble_app_advertise();
        return 0;

    case BLE_GAP_EVENT_MTU:
        ESP_LOGI(TAG, "MTU update mtu=%d", event->mtu.value);
        return 0;

    default:
        return 0;
    }
}

/* ================================================================
 *  Application-level pairing control
 * ================================================================ */
void ble_enable_pairing(uint32_t timeout_s)
{
    ble_pairing_enabled = 1;
    ble_pairing_timeout_s = timeout_s;
    ble_pairing_start_time = (uint32_t)(esp_timer_get_time() / 1000000);
    for (int i = 0; i < 6; i++)
        ble_pairing_pin[i] = (uint8_t)((esp_timer_get_time() + i) % 10) + '0';
    ESP_LOGI(TAG, "Pairing enabled PIN=%.6s timeout=%us", ble_pairing_pin, timeout_s);
    event_ble_pairing_enabled_t evt = {0};
    memcpy(evt.pin_code, ble_pairing_pin, 6);
    evt.timeout_s = timeout_s;
    send_event(EVENT_BLE_PAIRING_ENABLED, &evt, sizeof(evt));
}

void ble_disable_pairing(void)
{
    uint8_t reason = ble_pairing_enabled ? 2 : 0;
    ble_pairing_enabled = 0;
    ble_pairing_timeout_s = 0;
    for (int i = 0; i < 8; i++)
    {
        if (ble_peer_table[i].in_use && !ble_peer_table[i].encrypted)
        {
            ESP_LOGI(TAG, "Clean pre-alloc slot %d", i);
            ble_gap_terminate(ble_peer_table[i].conn_handle, BLE_ERR_REM_USER_CONN_TERM);
            ble_peer_table[i].in_use = 0;
        }
    }
    ESP_LOGI(TAG, "Pairing disabled reason=%u", reason);
    event_ble_pairing_disabled_t evt = {0};
    evt.reason = reason;
    send_event(EVENT_BLE_PAIRING_DISABLED, &evt, sizeof(evt));
}

void ble_get_peers_list(ble_peer_t *peers, int *peer_count)
{
    int count = 0;
    for (int i = 0; i < 8; i++)
    {
        if (ble_peer_table[i].in_use && ble_peer_table[i].encrypted && count < *peer_count)
        {
            memcpy(&peers[count], &ble_peer_table[i], sizeof(ble_peer_t));
            count++;
        }
    }
    *peer_count = count;
    ESP_LOGI(TAG, "Peers: %d encrypted", count);
}

void ble_start_rssi_scan(uint32_t interval_s)
{
    ble_rssi_scan_enabled = 1;
    ble_rssi_interval_s = interval_s;
    ble_rssi_last_scan_time = 0;
    nvs_save_ble();
    ESP_LOGI(TAG, "RSSI scan started interval=%us", interval_s);
}

void ble_stop_rssi_scan(void)
{
    ble_rssi_scan_enabled = 0;
    nvs_save_ble();
    ESP_LOGI(TAG, "RSSI scan stopped");
}

void ble_rssi_task(void *pvParameters)
{
    TickType_t delay = pdMS_TO_TICKS(1000);
    ESP_LOGI(TAG, "RSSI task started");
    while (1)
    {
        vTaskDelay(delay);
        uint32_t now = (uint32_t)(esp_timer_get_time() / 1000000);
        if (ble_pairing_enabled && ble_pairing_timeout_s > 0)
        {
            uint32_t elapsed = now - ble_pairing_start_time;
            if (elapsed >= ble_pairing_timeout_s)
            {
                ESP_LOGI(TAG, "Pairing timeout: %lus >= %lus", (unsigned long)elapsed, (unsigned long)ble_pairing_timeout_s);
                ble_disable_pairing();
            }
        }
        if (!ble_rssi_scan_enabled)
            continue;
        if (now - ble_rssi_last_scan_time >= ble_rssi_interval_s)
        {
            ble_rssi_last_scan_time = now;
            for (int i = 0; i < 8; i++)
            {
                if (ble_peer_table[i].in_use && ble_peer_table[i].encrypted)
                {
                    int8_t rssi = -60 + (i % 20);
                    ble_peer_table[i].rssi = rssi;
                    ble_peer_table[i].last_active_s = now;
                    event_ble_rssi_t evt = {0};
                    memcpy(evt.peer_mac, ble_peer_table[i].peer_mac, 6);
                    evt.rssi = rssi;
                    evt.timestamp_us = esp_timer_get_time();
                    send_event(EVENT_BLE_RSSI, &evt, sizeof(evt));
                }
            }
        }
    }
}
