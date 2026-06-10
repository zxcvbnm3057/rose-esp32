#ifndef NVS_STORE_H
#define NVS_STORE_H

#include <stdint.h>
#include <stdbool.h>

// NVS storage reuses the sync protocol structs (defined in iot_agent.h):
//   event_gpio_status_t  — GPIO config (gpio/mode/pull/edge/value/in_use/owner/adc)
//   event_uart_status_t  — UART config (uart_id/baudrate/…/in_use/owner)
// Runtime-only fields (owner, adc_raw, adc_mv) are zeroed on save and ignored on restore.

// All persistent keys live in ONE namespace "iot_cfg" to avoid fragmentation.

#define NVS_GPIO_MAX 31
#define NVS_UART_MAX 2

// ── BLE persistent config (no equivalent sync struct) ─────────
typedef struct
{
    uint8_t scan_enabled;
    uint32_t scan_interval_s;
} nvs_ble_cfg_t;

// ── Public API ────────────────────────────────────────────────

// ── Session version (incremented on every boot for sync tracking)
uint32_t nvs_load_session_version(void);
void nvs_save_session_version(uint32_t version);

// ── Individual saves (called from command handlers after config change)
void nvs_save_gpio_all(void);
void nvs_save_uart_all(void);
void nvs_save_ble(void);

// ── Batch save: GPIO + UART + BLE + session_version in one NVS transaction
void nvs_save_all(uint32_t session_version);

// ── Restore (opens NVS once, reads all keys)
void nvs_restore_all(void);

// ── Per-category restore (used internally, also available for targeted restore)
void nvs_restore_gpio_all(void);
void nvs_restore_uart_all(void);
void nvs_restore_ble(void);

#endif // NVS_STORE_H
