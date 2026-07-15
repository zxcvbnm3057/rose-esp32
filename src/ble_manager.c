#include "iot_agent.h"
#include "nvs_store.h"
#include "esp_log.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "host/ble_hs.h"
#include "host/ble_store.h"
#include "host/util/util.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"
#include "services/hid/ble_svc_hid.h"
#include "freertos/task.h"
#include "esp_timer.h"

static const char *TAG = "ble_manager";

static void ble_app_advertise(void);
static void ble_start_scan(void);

/* ================================================================
 *  In-range device table — unified presence model
 *
 *  A device is "in range" if we have seen recent activity from it,
 *  regardless of transport:
 *    - Android (connected): the GATT connection is alive → refreshed
 *      by the periodic liveness check in ble_rssi_task.
 *    - iOS (connectionless): after pairing it disconnects and just
 *      advertises. The controller auto-resolves its RPA to the bonded
 *      identity address, and the scan callback refreshes it.
 *
 *  A device leaves range when neither source refreshes it within
 *  IN_RANGE_TIMEOUT_S. The table is seeded at boot from the bond
 *  store so already-paired devices are tracked immediately.
 * ================================================================ */
// IN_RANGE_MAX is defined in iot_agent.h (shared with command_dispatcher).
#define IN_RANGE_TIMEOUT_S 10 // no heartbeat/adv within this window → out of range
#define CONN_HANDLE_NONE 0xFFFF
#define BLE_BOND_CAPACITY 5

static ble_in_range_device_t in_range_devices[IN_RANGE_MAX];

static ble_in_range_device_t *device_find_by_mac(const uint8_t mac[6])
{
    for (int i = 0; i < IN_RANGE_MAX; i++)
        if (in_range_devices[i].in_use &&
            memcmp(in_range_devices[i].device_mac, mac, 6) == 0)
            return &in_range_devices[i];
    return NULL;
}

static ble_in_range_device_t *device_find_by_handle(uint16_t handle)
{
    if (handle == CONN_HANDLE_NONE)
        return NULL;
    for (int i = 0; i < IN_RANGE_MAX; i++)
        if (in_range_devices[i].in_use &&
            in_range_devices[i].conn_handle == handle)
            return &in_range_devices[i];
    return NULL;
}

// Get an existing entry for this identity, or allocate a free slot.
static ble_in_range_device_t *device_get_or_add(const uint8_t mac[6])
{
    ble_in_range_device_t *d = device_find_by_mac(mac);
    if (d)
        return d;
    for (int i = 0; i < IN_RANGE_MAX; i++)
    {
        if (!in_range_devices[i].in_use)
        {
            memset(&in_range_devices[i], 0, sizeof(in_range_devices[i]));
            memcpy(in_range_devices[i].device_mac, mac, 6);
            in_range_devices[i].in_use = 1;
            in_range_devices[i].active = 0;
            in_range_devices[i].conn_handle = CONN_HANDLE_NONE;
            return &in_range_devices[i];
        }
    }
    return NULL; // table full
}

// Refresh activity for a device; emit DEVICE_IN_RANGE on 0→1 transition.
static void device_mark_active(ble_in_range_device_t *d, int8_t rssi,
                               uint16_t handle, uint32_t now)
{
    if (!d)
        return;
    d->last_active_s = now;
    d->rssi = rssi;
    if (handle != CONN_HANDLE_NONE)
        d->conn_handle = handle;
    if (!d->active)
    {
        d->active = 1;
        d->conn_time_s = now;
        event_ble_device_in_range_t evt = {0};
        memcpy(evt.device_mac, d->device_mac, 6);
        evt.rssi = rssi;
        send_event(EVENT_BLE_DEVICE_IN_RANGE, &evt, sizeof(evt));
        ESP_LOGI(TAG, "Device IN RANGE %02x:%02x:%02x:%02x:%02x:%02x rssi=%d",
                 d->device_mac[0], d->device_mac[1], d->device_mac[2],
                 d->device_mac[3], d->device_mac[4], d->device_mac[5], rssi);
    }
}

// Remove devices that have not been seen within the timeout window.
static void device_expire_stale(uint32_t now)
{
    for (int i = 0; i < IN_RANGE_MAX; i++)
    {
        ble_in_range_device_t *d = &in_range_devices[i];
        if (!d->in_use || !d->active)
            continue;
        if (now - d->last_active_s < IN_RANGE_TIMEOUT_S)
            continue;
        // Timed out → out of range. Keep the slot (device is still bonded)
        // but mark inactive so a later heartbeat/adv re-triggers IN_RANGE.
        d->active = 0;
        d->conn_handle = CONN_HANDLE_NONE;
        event_ble_device_out_of_range_t evt = {0};
        memcpy(evt.device_mac, d->device_mac, 6);
        evt.reason = 0; // 0 = presence timeout
        send_event(EVENT_BLE_DEVICE_OUT_OF_RANGE, &evt, sizeof(evt));
        ESP_LOGI(TAG, "Device OUT OF RANGE (timeout) %02x:%02x:%02x:%02x:%02x:%02x",
                 d->device_mac[0], d->device_mac[1], d->device_mac[2],
                 d->device_mac[3], d->device_mac[4], d->device_mac[5]);
    }
}

// Seed the table with all bonded identities so paired devices are
// tracked from boot even before we see their first heartbeat/adv.
static void device_seed_from_bonds(void)
{
    ble_addr_t addrs[IN_RANGE_MAX];
    int num = 0;
    int rc = ble_store_util_bonded_peers(addrs, &num, IN_RANGE_MAX);
    if (rc != 0)
    {
        ESP_LOGW(TAG, "bonded_peers failed; rc=%d", rc);
        return;
    }
    for (int i = 0; i < num; i++)
        device_get_or_add(addrs[i].val);
    ESP_LOGI(TAG, "Seeded %d bonded device(s) into in-range table", num);
}

uint8_t ble_pairing_enabled = 0;
uint32_t ble_pairing_timeout_s = 0;
uint32_t ble_pairing_start_time = 0;
uint8_t ble_pairing_pin[6] = {0};
uint8_t ble_rssi_scan_enabled = 0;
uint32_t ble_rssi_interval_s = 5;
uint32_t ble_rssi_last_scan_time = 0;
static volatile uint8_t ble_pairing_disable_pending = 0;
static volatile TickType_t ble_pairing_disable_at_tick = 0;
static uint8_t ble_gap_restart_suppressed = 0;
static uint16_t ble_pairing_conn_handle = CONN_HANDLE_NONE;

static void ble_schedule_pairing_disable(void)
{
    ble_pairing_disable_at_tick =
        xTaskGetTickCount() + pdMS_TO_TICKS(1000);
    ble_pairing_disable_pending = 1;
}

typedef struct
{
    bool found;
    ble_addr_t peer_addr;
    uint16_t bond_count;
} ble_lru_candidate_t;

static int ble_lru_find_cb(int obj_type, union ble_store_value *value,
                           void *cookie)
{
    ble_lru_candidate_t *candidate = cookie;
    const struct ble_store_value_sec *sec = &value->sec;

    if (obj_type != BLE_STORE_OBJ_TYPE_OUR_SEC)
        return 0;
    if (!candidate->found || sec->bond_count < candidate->bond_count)
    {
        candidate->found = true;
        candidate->peer_addr = sec->peer_addr;
        candidate->bond_count = sec->bond_count;
    }
    return 0;
}

// Rewriting OUR_SEC updates NimBLE's native bond_count in the existing bond
// record. PEER_SEC is intentionally untouched to avoid re-adding its IRK.
static void ble_lru_touch(const ble_addr_t *peer_addr)
{
    struct ble_store_key_sec key = {0};
    struct ble_store_value_sec value;
    key.peer_addr = *peer_addr;

    int rc = ble_store_read_our_sec(&key, &value);
    if (rc == 0)
    {
        rc = ble_store_write_our_sec(&value);
        if (rc != 0)
            ESP_LOGW(TAG, "Failed to update bond LRU; rc=%d", rc);
    }
}

static int ble_unpair_with_gap_paused(const ble_addr_t *peer_addr)
{
    ble_gap_restart_suppressed = 1;
    if (ble_gap_adv_active())
        ble_gap_adv_stop();
    if (ble_gap_disc_active())
        ble_gap_disc_cancel();

    int rc = ble_gap_unpair(peer_addr);
    ble_gap_restart_suppressed = 0;
    ble_app_advertise();
    ble_start_scan();
    return rc;
}

static int ble_lru_evict_if_full(void)
{
    ble_addr_t peers[BLE_BOND_CAPACITY];
    int peer_count = 0;
    int rc = ble_store_util_bonded_peers(peers, &peer_count,
                                         BLE_BOND_CAPACITY);
    if (rc != 0 || peer_count < BLE_BOND_CAPACITY)
        return rc;

    ble_lru_candidate_t candidate = {0};
    rc = ble_store_iterate(BLE_STORE_OBJ_TYPE_OUR_SEC,
                           ble_lru_find_cb, &candidate);
    if (rc != 0 || !candidate.found)
        return rc != 0 ? rc : BLE_HS_ENOENT;

    rc = ble_unpair_with_gap_paused(&candidate.peer_addr);
    if (rc != 0)
        return rc;

    ESP_LOGI(TAG, "Evicted LRU bond %02x:%02x:%02x:%02x:%02x:%02x count=%u",
             candidate.peer_addr.val[0], candidate.peer_addr.val[1],
             candidate.peer_addr.val[2], candidate.peer_addr.val[3],
             candidate.peer_addr.val[4], candidate.peer_addr.val[5],
             candidate.bond_count);
    return 0;
}

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

static void ble_host_task(void *pvParameters);
static void ble_on_sync(void);
static void ble_on_reset(int reason);
static void ble_restart_advertising(void);
static int ble_scan_event(struct ble_gap_event *event, void *arg);

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
    ESP_LOGI(TAG, "NimBLE host synced, starting advertising + scanning");
    // Seed the in-range table with already-bonded devices so presence is
    // tracked from boot. Their RPAs will be auto-resolved by the controller.
    device_seed_from_bonds();
    ble_app_advertise();
    // Run the observer (scan) role in parallel with advertising so we can
    // detect connectionless (iOS) bonded devices via their resolved adv.
    ble_start_scan();
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
 *  Passive scan (observer role) — detects connectionless bonded
 *  devices (iOS) via their advertisements. The controller resolves
 *  each RPA back to the bonded identity address automatically (its
 *  IRK is in the NVS bond store), so disc->addr matches a table
 *  entry directly. Runs forever, auto-restarting on completion, in
 *  parallel with advertising.
 * ================================================================ */
static void ble_start_scan(void)
{
    if (ble_gap_restart_suppressed || ble_gap_disc_active())
        return;

    struct ble_gap_disc_params scan_params = {0};
    scan_params.itvl = 0x0100;     // 160 ms
    scan_params.window = 0x0050;   // 50 ms — leave airtime for adv/conn
    scan_params.filter_policy = 0; // accept all; we match by identity below
    scan_params.limited = 0;
    scan_params.passive = 1;           // passive: we only need adv address + RSSI
    scan_params.filter_duplicates = 0; // need repeats to keep refreshing presence

    int rc = ble_gap_disc(BLE_ADDR_PUBLIC, BLE_HS_FOREVER,
                          &scan_params, ble_scan_event, NULL);
    if (rc != 0 && rc != BLE_HS_EALREADY)
        ESP_LOGW(TAG, "scan start failed; rc=%d", rc);
    else
        ESP_LOGI(TAG, "Scanning started (passive, resolving bonded RPAs)");
}

static int ble_scan_event(struct ble_gap_event *event, void *arg)
{
    switch (event->type)
    {
    case BLE_GAP_EVENT_DISC:
    {
        // The controller has already resolved a bonded peer's RPA to its
        // identity address, so a direct table lookup by address works.
        ble_in_range_device_t *d = device_find_by_mac(event->disc.addr.val);
        if (d)
        {
            uint32_t now = (uint32_t)(esp_timer_get_time() / 1000000);
            device_mark_active(d, event->disc.rssi, CONN_HANDLE_NONE, now);
            // Emit telemetry RSSI so the console can display live signal.
            event_ble_rssi_t evt = {0};
            memcpy(evt.device_mac, d->device_mac, 6);
            evt.rssi = event->disc.rssi;
            evt.timestamp_us = esp_timer_get_time();
            send_event(EVENT_BLE_RSSI, &evt, sizeof(evt));
        }
        return 0;
    }

    case BLE_GAP_EVENT_DISC_COMPLETE:
        // Scan cycle finished — restart to keep observing continuously.
        ESP_LOGD(TAG, "Scan complete (reason=%d), restarting", event->disc_complete.reason);
        if (!ble_gap_restart_suppressed)
            ble_start_scan();
        return 0;

    default:
        return 0;
    }
}

/* ================================================================
 *  GAP event handler — advertising/connection (peripheral role).
 *  PIN pairing and encryption flow unchanged; the peer table is now
 *  the unified in-range device table.
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

        // Existing bonds restore encryption; unbonded peers reach the
        // passkey callback and are rejected while pairing is disabled.
        {
            rc = ble_gap_security_initiate(event->connect.conn_handle);
            if (rc == 0)
            {
                ESP_LOGI(TAG, "Security initiated (%s)",
                         ble_pairing_enabled ? "pair or restore bond"
                                             : "restore existing bond");
            }
            else if (rc == BLE_HS_EALREADY)
            {
                ESP_LOGI(TAG, "Security already in progress");
            }
            else
            {
                ESP_LOGE(TAG, "security_initiate rc=%d — rejecting", rc);
                ble_gap_terminate(event->connect.conn_handle,
                                  BLE_ERR_REM_USER_CONN_TERM);
            }

            ble_app_advertise();
        }
        return 0;

    case BLE_GAP_EVENT_DISCONNECT:
        ESP_LOGI(TAG, "DISCONNECT reason=%d conn=%d",
                 event->disconnect.reason, event->disconnect.conn.conn_handle);
        {
            // A disconnect does NOT immediately mean out-of-range. An iOS
            // device intentionally drops the connection after pairing to go
            // connectionless — we keep tracking it via its advertisements.
            // Just detach the conn_handle; presence is governed by the
            // IN_RANGE_TIMEOUT_S window in ble_rssi_task. If the device is
            // truly gone, it stops advertising and times out there.
            uint16_t handle = event->disconnect.conn.conn_handle;
            if (ble_pairing_conn_handle == handle)
                ble_pairing_conn_handle = CONN_HANDLE_NONE;
            ble_in_range_device_t *d = device_find_by_handle(handle);
            if (d)
                d->conn_handle = CONN_HANDLE_NONE;
        }
        ble_app_advertise();
        return 0;

    case BLE_GAP_EVENT_ENC_CHANGE:
        ESP_LOGI(TAG, "ENC_CHANGE status=%d conn=%d",
                 event->enc_change.status, event->enc_change.conn_handle);
        if (event->enc_change.status == 0)
        {
            uint16_t handle = event->enc_change.conn_handle;
            struct ble_gap_conn_desc enc_desc;
            if (ble_gap_conn_find(handle, &enc_desc) == 0)
            {
                // Encryption complete → device is present via a live
                // connection. Add/refresh its table entry (Android path;
                // an iOS device will later disconnect and be tracked via
                // its resolved advertisements instead).
                uint32_t now = (uint32_t)(esp_timer_get_time() / 1000000);
                int8_t rssi = -50;
                ble_gap_conn_rssi(handle, &rssi);
                ble_in_range_device_t *d =
                    device_get_or_add(enc_desc.peer_id_addr.val);
                device_mark_active(d, rssi, handle, now);
                ble_lru_touch(&enc_desc.peer_id_addr);
            }
            ESP_LOGI(TAG, "Link encryption enabled");
            if (ble_pairing_enabled && ble_pairing_conn_handle == handle)
            {
                ESP_LOGI(TAG, "Passkey pairing encrypted; scheduling pairing disable");
                ble_pairing_conn_handle = CONN_HANDLE_NONE;
                ble_schedule_pairing_disable();
            }
        }
        else
        {
            ESP_LOGW(TAG, "Encryption FAILED status=%d — terminating", event->enc_change.status);
            ble_gap_terminate(event->enc_change.conn_handle, BLE_ERR_REM_USER_CONN_TERM);
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
            ble_pairing_conn_handle = event->passkey.conn_handle;
            rc = ble_lru_evict_if_full();
            if (rc != 0)
            {
                ESP_LOGE(TAG, "Cannot make room for new bond; rc=%d", rc);
                ble_gap_terminate(event->passkey.conn_handle,
                                  BLE_ERR_REM_USER_CONN_TERM);
                return 0;
            }
            struct ble_sm_io pkey = {0};
            pkey.action = BLE_SM_IOACT_DISP;
            uint32_t pin = 0;
            for (int i = 0; i < 6; i++)
                pin = pin * 10 + (ble_pairing_pin[i] - '0');
            pkey.passkey = pin;
            ESP_LOGI(TAG, "Injecting passkey %06lu", (unsigned long)pin);
            rc = ble_sm_inject_io(event->passkey.conn_handle, &pkey);
            ESP_LOGI(TAG, "ble_sm_inject_io rc=%d", rc);
            if (rc != 0)
                ble_gap_terminate(event->passkey.conn_handle,
                                  BLE_ERR_REM_USER_CONN_TERM);
        }
        else
        {
            ESP_LOGW(TAG, "Unsupported passkey action=%d — rejecting",
                     event->passkey.params.action);
            ble_gap_terminate(event->passkey.conn_handle,
                              BLE_ERR_REM_USER_CONN_TERM);
        }
        return 0;

    case BLE_GAP_EVENT_PARING_COMPLETE:
        ESP_LOGI(TAG, "PAIRING_COMPLETE status=%d conn=%d",
                 event->pairing_complete.status,
                 event->pairing_complete.conn_handle);
        if (event->pairing_complete.status == 0 && ble_pairing_enabled)
        {
            ble_pairing_conn_handle = CONN_HANDLE_NONE;
            ble_schedule_pairing_disable();
        }
        return 0;

    case BLE_GAP_EVENT_REPEAT_PAIRING:
        if (!ble_pairing_enabled)
        {
            ESP_LOGW(TAG, "REPEAT_PAIRING rejected; preserving existing bond");
            ble_gap_terminate(event->repeat_pairing.conn_handle,
                              BLE_ERR_REM_USER_CONN_TERM);
            return BLE_GAP_REPEAT_PAIRING_IGNORE;
        }
        ESP_LOGI(TAG, "REPEAT_PAIRING allowed — replacing old bond");
        rc = ble_gap_conn_find(event->repeat_pairing.conn_handle, &desc);
        if (rc != 0)
            return BLE_GAP_REPEAT_PAIRING_IGNORE;
        rc = ble_unpair_with_gap_paused(&desc.peer_id_addr);
        if (rc != 0)
            ESP_LOGE(TAG, "Repeat-pairing unpair failed; rc=%d", rc);
        return BLE_GAP_REPEAT_PAIRING_IGNORE;

    case BLE_GAP_EVENT_CONN_UPDATE:
        ESP_LOGI(TAG, "CONN_UPDATE status=%d", event->conn_update.status);
        return 0;

    case BLE_GAP_EVENT_CONN_UPDATE_REQ:
        ESP_LOGI(TAG, "CONN_UPDATE_REQ accepted");
        return 0;

    case BLE_GAP_EVENT_ADV_COMPLETE:
        ESP_LOGI(TAG, "ADV_COMPLETE reason=%d", event->adv_complete.reason);
        if (!ble_gap_restart_suppressed)
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
    ble_pairing_disable_pending = 0;
    ble_pairing_conn_handle = CONN_HANDLE_NONE;
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
    ble_pairing_disable_pending = 0;
    ble_pairing_conn_handle = CONN_HANDLE_NONE;
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

void ble_get_in_range_devices(ble_in_range_device_t *devices, int *device_count)
{
    int count = 0;
    for (int i = 0; i < IN_RANGE_MAX && count < *device_count; i++)
    {
        ble_in_range_device_t *d = &in_range_devices[i];
        if (!d->in_use || !d->active)
            continue;
        memcpy(devices[count].device_mac, d->device_mac, 6);
        devices[count].rssi = d->rssi;
        devices[count].conn_handle = d->conn_handle;
        devices[count].conn_time_s = d->conn_time_s;
        devices[count].last_active_s = d->last_active_s;
        devices[count].in_use = 1;
        devices[count].active = 1;
        count++;
    }
    *device_count = count;
    ESP_LOGI(TAG, "In-range devices: %d", count);
}

int ble_in_range_device_count(void)
{
    int count = 0;
    for (int i = 0; i < IN_RANGE_MAX; i++)
        if (in_range_devices[i].in_use && in_range_devices[i].active)
            count++;
    return count;
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

int ble_delete_bond(const uint8_t device_mac[6])
{
    ble_in_range_device_t *device = device_find_by_mac(device_mac);
    uint16_t conn_handle = device ? device->conn_handle : CONN_HANDLE_NONE;
    bool was_active = device && device->active;
    ble_addr_t peer_addr = {.type = BLE_ADDR_PUBLIC};
    memcpy(peer_addr.val, device_mac, sizeof(peer_addr.val));

    int rc = ble_store_util_delete_peer(&peer_addr);
    if (rc != 0)
    {
        peer_addr.type = BLE_ADDR_RANDOM;
        rc = ble_store_util_delete_peer(&peer_addr);
    }
    if (rc != 0)
    {
        ESP_LOGW(TAG, "Failed to delete bond; rc=%d", rc);
        return rc;
    }

    if (conn_handle != CONN_HANDLE_NONE)
        ble_gap_terminate(conn_handle, BLE_ERR_REM_USER_CONN_TERM);
    if (was_active)
    {
        event_ble_device_out_of_range_t evt = {0};
        memcpy(evt.device_mac, device_mac, sizeof(evt.device_mac));
        evt.reason = 1; // bond deleted
        send_event(EVENT_BLE_DEVICE_OUT_OF_RANGE, &evt, sizeof(evt));
    }
    if (device)
        memset(device, 0, sizeof(*device));
    ESP_LOGI(TAG, "Deleted BLE bond");
    return 0;
}

void ble_rssi_task(void *pvParameters)
{
    TickType_t delay = pdMS_TO_TICKS(1000);
    ESP_LOGI(TAG, "RSSI task started");
    while (1)
    {
        vTaskDelay(delay);
        uint32_t now = (uint32_t)(esp_timer_get_time() / 1000000);
        if (ble_pairing_disable_pending &&
            (int32_t)(xTaskGetTickCount() - ble_pairing_disable_at_tick) >= 0)
        {
            ESP_LOGI(TAG, "Bond persistence grace period complete");
            ble_disable_pairing();
        }
        if (ble_pairing_enabled && ble_pairing_timeout_s > 0)
        {
            uint32_t elapsed = now - ble_pairing_start_time;
            if (elapsed >= ble_pairing_timeout_s)
            {
                ESP_LOGI(TAG, "Pairing timeout: %lus >= %lus", (unsigned long)elapsed, (unsigned long)ble_pairing_timeout_s);
                ble_disable_pairing();
            }
        }
        // Liveness for connected (Android) devices: while the GATT link is
        // up, poll its RSSI. A successful poll both refreshes presence and
        // emits telemetry. iOS devices are refreshed by the scan callback
        // instead, so they are skipped here (conn_handle == NONE).
        if (now - ble_rssi_last_scan_time >= 5)
        {
            ble_rssi_last_scan_time = now;
            for (int i = 0; i < IN_RANGE_MAX; i++)
            {
                ble_in_range_device_t *dev = &in_range_devices[i];
                if (!dev->in_use || dev->conn_handle == CONN_HANDLE_NONE)
                    continue;
                struct ble_gap_conn_desc d;
                if (ble_gap_conn_find(dev->conn_handle, &d) != 0)
                    continue; // link gone; timeout path will expire it
                int8_t rssi = -60;
                ble_gap_conn_rssi(dev->conn_handle, &rssi);
                device_mark_active(dev, rssi, dev->conn_handle, now);
                event_ble_rssi_t evt = {0};
                memcpy(evt.device_mac, d.peer_id_addr.val, 6);
                evt.rssi = rssi;
                evt.timestamp_us = esp_timer_get_time();
                send_event(EVENT_BLE_RSSI, &evt, sizeof(evt));
            }
        }

        // Expire devices whose last activity (heartbeat or resolved adv) is
        // older than the presence window → emit DEVICE_OUT_OF_RANGE.
        device_expire_stale(now);
    }
}
