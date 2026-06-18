#include "iot_agent.h"
#include "nvs_store.h"
#include "esp_log.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"
#include "services/hid/ble_svc_hid.h"
#include "freertos/task.h"
#include "esp_timer.h"

static const char *TAG = "ble_manager";

#define ENCRYPTED_MAX 16
static uint16_t encrypted_handles[ENCRYPTED_MAX];
static int encrypted_count = 0;

static void encrypted_add(uint16_t conn_handle)
{
    if (encrypted_count < ENCRYPTED_MAX)
        encrypted_handles[encrypted_count++] = conn_handle;
}

static void encrypted_remove(uint16_t conn_handle)
{
    for (int i = 0; i < encrypted_count; i++)
    {
        if (encrypted_handles[i] == conn_handle)
        {
            encrypted_handles[i] = encrypted_handles[--encrypted_count];
            return;
        }
    }
}

uint8_t ble_pairing_enabled = 0;
uint32_t ble_pairing_timeout_s = 0;
uint32_t ble_pairing_start_time = 0;
uint8_t ble_pairing_pin[6] = {0};
uint8_t ble_rssi_scan_enabled = 0;
uint32_t ble_rssi_interval_s = 5;
uint32_t ble_rssi_last_scan_time = 0;

/* ================================================================
 *  HID Report Map — Media / Consumer Control (no input provided)
 *  Declares the device as a media-control HID peripheral so that
 *  phones/PCs see it as a remote/media device, matching the
 *  mediaReportMap from the ESP-IDF HID device example.
 * ================================================================ */
static const uint8_t hid_media_report_map[] = {
    0x05, 0x0C, // Usage Page (Consumer)
    0x09, 0x01, // Usage (Consumer Control)
    0xA1, 0x01, // Collection (Application)
    0x85, 0x03, //   Report ID (3)
    0x09, 0x02, //   Usage (Numeric Key Pad)
    0xA1, 0x02, //   Collection (Logical)
    0x05, 0x09, //     Usage Page (Button)
    0x19, 0x01, //     Usage Minimum (0x01)
    0x29, 0x0A, //     Usage Maximum (0x0A)
    0x15, 0x01, //     Logical Minimum (1)
    0x25, 0x0A, //     Logical Maximum (10)
    0x75, 0x04, //     Report Size (4)
    0x95, 0x01, //     Report Count (1)
    0x81, 0x00, //     Input (Data,Array,Abs)
    0xC0,       //   End Collection
    0x05, 0x0C, //   Usage Page (Consumer)
    0x09, 0x86, //   Usage (Channel)
    0x15, 0xFF, //   Logical Minimum (-1)
    0x25, 0x01, //   Logical Maximum (1)
    0x75, 0x02, //   Report Size (2)
    0x95, 0x01, //   Report Count (1)
    0x81, 0x46, //   Input (Data,Var,Rel,Null State)
    0x09, 0xE9, //   Usage (Volume Increment)
    0x09, 0xEA, //   Usage (Volume Decrement)
    0x15, 0x00, //   Logical Minimum (0)
    0x75, 0x01, //   Report Size (1)
    0x95, 0x02, //   Report Count (2)
    0x81, 0x02, //   Input (Data,Var,Abs)
    0x09, 0xE2, //   Usage (Mute)
    0x09, 0x30, //   Usage (Power)
    0x09, 0x83, //   Usage (Recall Last)
    0x09, 0x81, //   Usage (Assign Selection)
    0x09, 0xB0, //   Usage (Play)
    0x09, 0xB1, //   Usage (Pause)
    0x09, 0xB2, //   Usage (Record)
    0x09, 0xB3, //   Usage (Fast Forward)
    0x09, 0xB4, //   Usage (Rewind)
    0x09, 0xB5, //   Usage (Scan Next Track)
    0x09, 0xB6, //   Usage (Scan Previous Track)
    0x09, 0xB7, //   Usage (Stop)
    0x15, 0x01, //   Logical Minimum (1)
    0x25, 0x0C, //   Logical Maximum (12)
    0x75, 0x04, //   Report Size (4)
    0x95, 0x01, //   Report Count (1)
    0x81, 0x00, //   Input (Data,Array,Abs)
    0x09, 0x80, //   Usage (Selection)
    0xA1, 0x02, //   Collection (Logical)
    0x05, 0x09, //     Usage Page (Button)
    0x19, 0x01, //     Usage Minimum (0x01)
    0x29, 0x03, //     Usage Maximum (0x03)
    0x15, 0x01, //     Logical Minimum (1)
    0x25, 0x03, //     Logical Maximum (3)
    0x75, 0x02, //     Report Size (2)
    0x81, 0x00, //     Input (Data,Array,Abs)
    0xC0,       //   End Collection
    0x81, 0x03, //   Input (Const,Var,Abs)
    0xC0        // End Collection
};

static int ble_gap_event(struct ble_gap_event *event, void *arg);

// NimBLE store init — available at link time even if not in headers
extern void ble_store_config_init(void);

static void ble_app_advertise(void);
static void ble_host_task(void *pvParameters);
static void ble_on_sync(void);
static void ble_on_reset(int reason);
static void ble_restart_advertising(void);

/* ================================================================
 *  Init — NimBLE HID peripheral pattern (media device, no input)
 *  Follows official NimBLE HID + bleprph example patterns.
 *  Keeps original PIN pairing & RSSI signal detection unchanged.
 * ================================================================ */
void ble_manager_init(void)
{
    ESP_LOGI(TAG, "BLE Manager initializing...");

    ESP_ERROR_CHECK(nimble_port_init());

    ble_hs_cfg.reset_cb = ble_on_reset;
    ble_hs_cfg.sync_cb = ble_on_sync;
    ble_hs_cfg.store_status_cb = ble_store_util_status_rr;

    // Security — keep existing PIN pairing mode unchanged
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

    struct ble_svc_hid_params hid_params = {0};
    hid_params.report_map_len = sizeof(hid_media_report_map);
    memcpy(hid_params.report_map, hid_media_report_map, hid_params.report_map_len);
    // No boot keyboard/mouse, no protocol mode — pure report-mode media device
    hid_params.proto_mode_present = 0;
    hid_params.kbd_inp_present = 0;
    hid_params.kbd_out_present = 0;
    hid_params.mouse_inp_present = 0;
    ble_svc_hid_add(hid_params);

    ble_svc_hid_init();

    nimble_port_freertos_init(ble_host_task);

    ESP_LOGI(TAG, "BLE Manager initialized (HID media, advertising ON, PIN auth required)");
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
 *  Advertising — two modes (discoverability only):
 *   - Pairing mode ON  : general-discoverable, so new devices can
 *                        be found and start the PIN pairing flow.
 *   - Pairing mode OFF : non-discoverable. The device is still
 *                        connectable (so already-paired devices can
 *                        reconnect), but new devices cannot discover
 *                        it via scanning. New devices that connect
 *                        anyway are rejected at the app layer:
 *                        PASSKEY_ACTION is refused while pairing is
 *                        off, and unencrypted peers never enter the
 *                        peer list — so they can do nothing useful.
 * ================================================================ */
static void ble_app_advertise(void)
{
    struct ble_gap_adv_params adv_params;
    struct ble_hs_adv_fields fields;
    int rc;

    memset(&fields, 0, sizeof(fields));
    fields.flags = BLE_HS_ADV_F_BREDR_UNSUP;
    if (ble_pairing_enabled)
        fields.flags |= BLE_HS_ADV_F_DISC_GEN;
    fields.tx_pwr_lvl_is_present = 1;
    fields.tx_pwr_lvl = BLE_HS_ADV_TX_PWR_LVL_AUTO;
    fields.name = (uint8_t *)"ESP32-IoT";
    fields.name_len = strlen("ESP32-IoT");
    fields.name_is_complete = 1;

    // Declare HID service appearance — Generic HID (0x03C0)
    fields.appearance = 0x03C0; // ESP_HID_APPEARANCE_GENERIC
    fields.appearance_is_present = 1;

    // Advertise HID service UUID (0x1812) instead of generic GAP/GATT
    fields.uuids16 = (ble_uuid16_t[]){
        BLE_UUID16_INIT(BLE_SVC_HID_UUID16) // 0x1812
    };
    fields.num_uuids16 = 1;
    fields.uuids16_is_complete = 1;

    rc = ble_gap_adv_set_fields(&fields);
    if (rc != 0)
    {
        ESP_LOGE(TAG, "adv_set_fields failed; rc=%d", rc);
        return;
    }

    memset(&adv_params, 0, sizeof(adv_params));
    adv_params.conn_mode = BLE_GAP_CONN_MODE_UND;
    adv_params.disc_mode = ble_pairing_enabled ? BLE_GAP_DISC_MODE_GEN
                                               : BLE_GAP_DISC_MODE_NON;
    ESP_LOGI(TAG, "Advertising: %s",
             ble_pairing_enabled ? "DISCOVERABLE (pairing mode)"
                                 : "NON-DISCOVERABLE (paired devices reconnect only)");

    rc = ble_gap_adv_start(BLE_ADDR_PUBLIC, NULL, BLE_HS_FOREVER,
                           &adv_params, ble_gap_event, NULL);
    if (rc != 0)
    {
        ESP_LOGE(TAG, "adv_start failed; rc=%d", rc);
        return;
    }
}

/* ================================================================
 *  Restart advertising — stop the current advertisement (if any)
 *  and re-start it so the discoverable/whitelist mode is re-applied.
 *  Called whenever pairing mode is toggled at runtime.
 * ================================================================ */
static void ble_restart_advertising(void)
{
    if (ble_gap_adv_active())
        ble_gap_adv_stop();
    ble_app_advertise();
}

/* ================================================================
 *  GAP event handler — follows bleprph patterns
 *  PIN pairing, peer table, encryption, and RSSI logic UNCHANGED.
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

        // Accept connection
        {
            if (ble_pairing_enabled)
            {
                rc = ble_gap_security_initiate(event->connect.conn_handle);
                if (rc == 0)
                {
                    ESP_LOGI(TAG, "Security initiated, waiting for passkey...");
                }
                else if (rc == BLE_HS_EALREADY)
                {
                    // Central (e.g. a PC) already started pairing/encryption.
                    // This is the normal path for a central-initiated bond —
                    // let it drive the SMP ceremony instead of rejecting.
                    ESP_LOGI(TAG, "Security already in progress (central-initiated) — continuing");
                }
                else
                {
                    ESP_LOGE(TAG, "security_initiate rc=%d — rejecting", rc);
                    ble_gap_terminate(event->connect.conn_handle, BLE_ERR_REM_USER_CONN_TERM);
                }
            }
            else
                ESP_LOGI(TAG, "Pairing disabled — accepting without new pairing");

            ble_app_advertise();
        }
        return 0;

    case BLE_GAP_EVENT_DISCONNECT:
        ESP_LOGI(TAG, "DISCONNECT reason=%d conn=%d",
                 event->disconnect.reason, event->disconnect.conn.conn_handle);
        {
            uint16_t handle = event->disconnect.conn.conn_handle;
            encrypted_remove(handle);
            event_ble_peer_disconnected_t evt = {0};
            // 连接此刻已断开，ble_gap_conn_find(handle) 会失败导致 MAC 全为 0。
            // disconnect 事件本身携带对端连接描述符，直接取身份地址即可。
            memcpy(evt.peer_mac, event->disconnect.conn.peer_id_addr.val, 6);
            evt.reason = event->disconnect.reason;
            send_event(EVENT_BLE_PEER_DISCONNECTED, &evt, sizeof(evt));
        }
        ble_app_advertise();
        return 0;

    case BLE_GAP_EVENT_ENC_CHANGE:
        ESP_LOGI(TAG, "ENC_CHANGE status=%d conn=%d",
                 event->enc_change.status, event->enc_change.conn_handle);
        if (event->enc_change.status == 0)
        {
            uint16_t handle = event->enc_change.conn_handle;
            encrypted_add(handle);
            struct ble_gap_conn_desc enc_desc;
            event_ble_peer_connected_t evt = {0};
            if (ble_gap_conn_find(handle, &enc_desc) == 0)
                memcpy(evt.peer_mac, enc_desc.peer_id_addr.val, 6);
            evt.rssi = -50;
            send_event(EVENT_BLE_PEER_CONNECTED, &evt, sizeof(evt));
            ESP_LOGI(TAG, "Peer connected (encryption OK)");
            if (ble_pairing_enabled)
            {
                // Pairing finished: auto-disable pin. ble_disable_pairing()
                // clears the flag, emits PAIRING_DISABLED, and re-advertises
                // as non-discoverable so no new devices can find/pair.
                ESP_LOGI(TAG, "Auto-disabling pairing after successful bond");
                ble_disable_pairing();
            }
        }
        else
        {
            ESP_LOGW(TAG, "Encryption FAILED status=%d — cleaning up", event->enc_change.status);
            uint16_t handle = event->enc_change.conn_handle;
            encrypted_remove(handle);
            struct ble_gap_conn_desc enc_desc;
            event_ble_peer_disconnected_t evt = {0};
            if (ble_gap_conn_find(handle, &enc_desc) == 0)
                memcpy(evt.peer_mac, enc_desc.peer_id_addr.val, 6);
            evt.reason = event->enc_change.status;
            send_event(EVENT_BLE_PEER_DISCONNECTED, &evt, sizeof(evt));
            ble_gap_terminate(handle, BLE_ERR_REM_USER_CONN_TERM);
        }
        return 0;

    case BLE_GAP_EVENT_PASSKEY_ACTION:
        ESP_LOGI(TAG, "PASSKEY_ACTION action=%d", event->passkey.params.action);
        if (!ble_pairing_enabled)
        {
            ESP_LOGW(TAG, "Pairing disabled — rejecting");
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
        ESP_LOGI(TAG, "REPEAT_PAIRING — deleting old bond, retrying");
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
 *  Application-level pairing control — UNCHANGED
 * ================================================================ */
void ble_enable_pairing(uint16_t cmd_id, uint32_t timeout_s)
{
    ble_pairing_enabled = 1;
    ble_pairing_timeout_s = timeout_s;
    ble_pairing_start_time = (uint32_t)(esp_timer_get_time() / 1000000);
    for (int i = 0; i < 6; i++)
        ble_pairing_pin[i] = (uint8_t)((esp_timer_get_time() + i) % 10) + '0';
    ESP_LOGI(TAG, "Pairing enabled PIN=%.6s timeout=%us", ble_pairing_pin, timeout_s);
    event_ble_pairing_enabled_t evt = {0};
    evt.cmd_id = cmd_id;
    memcpy(evt.pin_code, ble_pairing_pin, 6);
    evt.timeout_s = timeout_s;
    send_event(EVENT_BLE_PAIRING_ENABLED, &evt, sizeof(evt));
    // Switch advertising to discoverable mode so new devices can pair.
    ble_restart_advertising();
}

void ble_disable_pairing(void)
{
    uint8_t reason = ble_pairing_enabled ? 2 : 0;
    ble_pairing_enabled = 0;
    ble_pairing_timeout_s = 0;
    ESP_LOGI(TAG, "Pairing disabled reason=%u", reason);
    event_ble_pairing_disabled_t evt = {0};
    evt.reason = reason;
    send_event(EVENT_BLE_PAIRING_DISABLED, &evt, sizeof(evt));
    // Switch advertising back to non-discoverable: new devices can no
    // longer find the device; already-paired devices can still reconnect.
    ble_restart_advertising();
}

void ble_get_peers_list(ble_peer_t *peers, int *peer_count)
{
    int count = 0;
    for (int i = 0; i < encrypted_count && count < *peer_count; i++)
    {
        uint16_t handle = encrypted_handles[i];
        struct ble_gap_conn_desc desc;
        if (ble_gap_conn_find(handle, &desc) != 0)
            continue;
        memcpy(peers[count].peer_mac, desc.peer_id_addr.val, 6);
        int8_t rssi = -60;
        ble_gap_conn_rssi(handle, &rssi);
        peers[count].rssi = rssi;
        peers[count].conn_handle = handle;
        count++;
    }
    *peer_count = count;
    ESP_LOGI(TAG, "Peers: %d encrypted", count);
}

int ble_encrypted_peer_count(void)
{
    return encrypted_count;
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
        // Always monitor RSSI for connected (encrypted) peers
        if (now - ble_rssi_last_scan_time >= 5)
        {
            ble_rssi_last_scan_time = now;
            for (int i = 0; i < encrypted_count; i++)
            {
                uint16_t handle = encrypted_handles[i];
                struct ble_gap_conn_desc d;
                if (ble_gap_conn_find(handle, &d) != 0)
                    continue;
                int8_t rssi = -60;
                ble_gap_conn_rssi(handle, &rssi);
                event_ble_rssi_t evt = {0};
                memcpy(evt.peer_mac, d.peer_id_addr.val, 6);
                evt.rssi = rssi;
                evt.timestamp_us = esp_timer_get_time();
                send_event(EVENT_BLE_RSSI, &evt, sizeof(evt));
            }
        }
    }
}
