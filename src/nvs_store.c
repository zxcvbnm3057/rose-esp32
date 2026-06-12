#include "nvs_store.h"
#include "iot_agent.h"
#include <string.h>
#include "esp_log.h"
#include "nvs_flash.h"
#include "nvs.h"
#include "driver/gpio.h"
#include "driver/uart.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "nvs_store";
static const char *NVS_CFG_NS = "iot_cfg";

// All persistent keys in ONE namespace
static const char *KEY_GPIO_CFG = "gpio_cfg";
static const char *KEY_UART_CFG = "uart_cfg";
static const char *KEY_BLE_SCAN_EN = "ble_scan_en";
static const char *KEY_BLE_SCAN_INT = "ble_scan_int";
static const char *KEY_SESSION_VER = "session_ver"; // was "session_version" in old "iot_agent" NS

// ── Internal helpers ──────────────────────────────────────────

static uart_word_length_t nvs_map_data_bits(uint8_t data_bits)
{
    switch (data_bits)
    {
    case 5:
        return UART_DATA_5_BITS;
    case 6:
        return UART_DATA_6_BITS;
    case 7:
        return UART_DATA_7_BITS;
    case 8:
    default:
        return UART_DATA_8_BITS;
    }
}

static uart_parity_t nvs_map_parity(uint8_t parity)
{
    switch (parity)
    {
    case 1:
        return UART_PARITY_EVEN;
    case 2:
        return UART_PARITY_ODD;
    case 0:
    default:
        return UART_PARITY_DISABLE;
    }
}

static uart_stop_bits_t nvs_map_stop_bits(uint8_t stop_bits)
{
    switch (stop_bits)
    {
    case 2:
        return UART_STOP_BITS_2;
    case 1:
    default:
        return UART_STOP_BITS_1;
    }
}

// ── Session version (moved from command_dispatcher) ───────────

uint32_t nvs_load_session_version(void)
{
    nvs_handle_t handle;
    uint32_t version = 0;
    if (nvs_open(NVS_CFG_NS, NVS_READONLY, &handle) == ESP_OK)
    {
        nvs_get_u32(handle, KEY_SESSION_VER, &version);
        nvs_close(handle);
    }
    return version;
}

void nvs_save_session_version(uint32_t version)
{
    nvs_handle_t handle;
    if (nvs_open(NVS_CFG_NS, NVS_READWRITE, &handle) == ESP_OK)
    {
        nvs_set_u32(handle, KEY_SESSION_VER, version);
        nvs_commit(handle);
        nvs_close(handle);
    }
}

// ── Internal save helpers (handle already open, caller commits/closes) ──

static void _nvs_save_gpio_blob(nvs_handle_t handle, int *out_count)
{
    // Allocate on heap to avoid stack overflow in main task
    event_gpio_status_t *cfgs = (event_gpio_status_t *)malloc(NVS_GPIO_MAX * sizeof(event_gpio_status_t));
    if (!cfgs)
    {
        if (out_count)
            *out_count = 0;
        return;
    }
    int count = 0;
    for (int i = 0; i < NVS_GPIO_MAX; i++)
    {
        if (gpio_table[i].mode != 0xFF && gpio_table[i].in_use)
        {
            cfgs[count].gpio = (uint8_t)i;
            cfgs[count].mode = gpio_table[i].mode;
            cfgs[count].pull = gpio_table[i].pull;
            cfgs[count].edge = gpio_table[i].edge;
            cfgs[count].value = gpio_table[i].value;
            cfgs[count].in_use = gpio_table[i].in_use;
            cfgs[count].owner = 0;
            cfgs[count].adc_raw = 0;
            cfgs[count].adc_mv = 0;
            count++;
        }
    }
    size_t blob_size = sizeof(uint8_t) + count * sizeof(event_gpio_status_t);
    uint8_t *blob = (uint8_t *)malloc(blob_size);
    if (blob)
    {
        blob[0] = (uint8_t)count;
        if (count > 0)
            memcpy(blob + 1, cfgs, count * sizeof(event_gpio_status_t));
        nvs_set_blob(handle, KEY_GPIO_CFG, blob, blob_size);
        free(blob);
    }
    free(cfgs);
    if (out_count)
        *out_count = count;
}

static void _nvs_save_uart_blob(nvs_handle_t handle, int *out_count)
{
    // Allocate on heap to avoid stack overflow in main task
    event_uart_status_t *cfgs = (event_uart_status_t *)malloc(NVS_UART_MAX * sizeof(event_uart_status_t));
    if (!cfgs)
    {
        if (out_count)
            *out_count = 0;
        return;
    }
    int count = 0;
    for (int i = 0; i < NVS_UART_MAX; i++)
    {
        if (uart_table[i].in_use)
        {
            cfgs[count].uart_id = (uint8_t)i;
            cfgs[count].baudrate = uart_table[i].baudrate;
            cfgs[count].data_bits = uart_table[i].data_bits;
            cfgs[count].parity = uart_table[i].parity;
            cfgs[count].stop_bits = uart_table[i].stop_bits;
            cfgs[count].tx_gpio = uart_table[i].tx_pin;
            cfgs[count].rx_gpio = uart_table[i].rx_pin;
            cfgs[count].in_use = uart_table[i].in_use;
            cfgs[count].owner = 0;
            count++;
        }
    }
    size_t blob_size = sizeof(uint8_t) + count * sizeof(event_uart_status_t);
    uint8_t *blob = (uint8_t *)malloc(blob_size);
    if (blob)
    {
        blob[0] = (uint8_t)count;
        if (count > 0)
            memcpy(blob + 1, cfgs, count * sizeof(event_uart_status_t));
        nvs_set_blob(handle, KEY_UART_CFG, blob, blob_size);
        free(blob);
    }
    free(cfgs);
    if (out_count)
        *out_count = count;
}

static void _nvs_save_ble_keys(nvs_handle_t handle)
{
    nvs_set_u8(handle, KEY_BLE_SCAN_EN, ble_rssi_scan_enabled);
    nvs_set_u32(handle, KEY_BLE_SCAN_INT, ble_rssi_interval_s);
}

// ── Public save wrappers (open/handle/commit/close) ──────────

void nvs_save_gpio_all(void)
{
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_CFG_NS, NVS_READWRITE, &handle);
    if (err != ESP_OK)
    {
        ESP_LOGW(TAG, "nvs_open gpio failed: %d", err);
        return;
    }
    int count = 0;
    _nvs_save_gpio_blob(handle, &count);
    err = nvs_commit(handle);
    nvs_close(handle);
    if (err == ESP_OK)
    {
        ESP_LOGI(TAG, "GPIO configs saved (%d pins)", count);
    }
    else
    {
        ESP_LOGW(TAG, "GPIO config save failed: %d", err);
    }
}

// ── Internal restore helpers (handle already open, caller closes) ──

static int _nvs_restore_gpio(nvs_handle_t handle)
{
    size_t required_size = 0;
    esp_err_t err = nvs_get_blob(handle, KEY_GPIO_CFG, NULL, &required_size);
    if (err != ESP_OK || required_size == 0)
    {
        ESP_LOGI(TAG, "No GPIO blob in NVS");
        return 0;
    }

    uint8_t *blob = (uint8_t *)malloc(required_size);
    if (!blob)
        return 0;
    err = nvs_get_blob(handle, KEY_GPIO_CFG, blob, &required_size);
    if (err != ESP_OK)
    {
        ESP_LOGW(TAG, "GPIO blob read failed: %d", err);
        free(blob);
        return 0;
    }

    uint8_t count = blob[0];
    event_gpio_status_t *cfgs = (event_gpio_status_t *)(blob + 1);
    int restored = 0;
    bool isr_installed = false;

    for (int i = 0; i < count; i++)
    {
        uint8_t gpio = cfgs[i].gpio;
        if (gpio >= NVS_GPIO_MAX)
            continue;

        // Update gpio_table
        xSemaphoreTake(resource_mutex, portMAX_DELAY);
        gpio_table[gpio].mode = cfgs[i].mode;
        gpio_table[gpio].pull = cfgs[i].pull;
        gpio_table[gpio].edge = cfgs[i].edge;
        gpio_table[gpio].in_use = cfgs[i].in_use;
        gpio_table[gpio].owner = 0;
        xSemaphoreGive(resource_mutex);

        // Apply hardware config
        gpio_config_t io_conf = {};
        io_conf.intr_type = GPIO_INTR_DISABLE;
        io_conf.pin_bit_mask = (1ULL << gpio);

        switch (cfgs[i].mode)
        {
        case IOT_GPIO_MODE_OUTPUT:
            io_conf.mode = GPIO_MODE_OUTPUT;
            break;
        case IOT_GPIO_MODE_INPUT:
        case IOT_GPIO_MODE_ADC:
        case IOT_GPIO_MODE_SIGNAL:
            io_conf.mode = GPIO_MODE_INPUT;
            break;
        case IOT_GPIO_MODE_INTERRUPT:
            io_conf.mode = GPIO_MODE_INPUT;
            io_conf.intr_type = GPIO_INTR_ANYEDGE;
            break;
        default:
            continue;
        }

        io_conf.pull_down_en = (cfgs[i].pull == 1) ? GPIO_PULLDOWN_ENABLE : GPIO_PULLDOWN_DISABLE;
        io_conf.pull_up_en = (cfgs[i].pull == 2) ? GPIO_PULLUP_ENABLE : GPIO_PULLUP_DISABLE;
        gpio_config(&io_conf);

        if (cfgs[i].mode == IOT_GPIO_MODE_OUTPUT)
        {
            gpio_set_level(gpio, cfgs[i].value);
            gpio_table[gpio].value = cfgs[i].value;
        }

        if (cfgs[i].mode == IOT_GPIO_MODE_INTERRUPT)
        {
            if (!isr_installed)
            {
                gpio_install_isr_service(0);
                isr_installed = true;
            }
            gpio_isr_handler_add(gpio, gpio_isr_handler, (void *)(uintptr_t)gpio);
        }

        restored++;
        ESP_LOGI(TAG, "Restored GPIO%d mode=%d pull=%d edge=%d val=%d",
                 gpio, cfgs[i].mode, cfgs[i].pull, cfgs[i].edge, cfgs[i].value);
    }

    free(blob);
    return restored;
}

void nvs_restore_gpio_all(void)
{
    nvs_handle_t handle;
    if (nvs_open(NVS_CFG_NS, NVS_READONLY, &handle) != ESP_OK)
    {
        ESP_LOGI(TAG, "No GPIO config in NVS (first boot or erased)");
        return;
    }
    int n = _nvs_restore_gpio(handle);
    nvs_close(handle);
    ESP_LOGI(TAG, "GPIO restore complete: %d pins", n);
}

// ── UART persistence ──────────────────────────────────────────

void nvs_save_uart_all(void)
{
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_CFG_NS, NVS_READWRITE, &handle);
    if (err != ESP_OK)
    {
        ESP_LOGW(TAG, "nvs_open uart failed: %d", err);
        return;
    }
    int count = 0;
    _nvs_save_uart_blob(handle, &count);
    err = nvs_commit(handle);
    nvs_close(handle);
    if (err == ESP_OK)
    {
        ESP_LOGI(TAG, "UART configs saved (%d ports)", count);
    }
    else
    {
        ESP_LOGW(TAG, "UART config save failed: %d", err);
    }
}

// ── Internal UART restore ─────────────────────────────────────

static int _nvs_restore_uart(nvs_handle_t handle)
{
    size_t required_size = 0;
    esp_err_t err = nvs_get_blob(handle, KEY_UART_CFG, NULL, &required_size);
    if (err != ESP_OK || required_size == 0)
    {
        ESP_LOGI(TAG, "No UART blob in NVS");
        return 0;
    }

    uint8_t *blob = (uint8_t *)malloc(required_size);
    if (!blob)
        return 0;
    err = nvs_get_blob(handle, KEY_UART_CFG, blob, &required_size);
    if (err != ESP_OK)
    {
        ESP_LOGW(TAG, "UART blob read failed: %d", err);
        free(blob);
        return 0;
    }

    uint8_t count = blob[0];
    event_uart_status_t *cfgs = (event_uart_status_t *)(blob + 1);
    int restored = 0;

    for (int i = 0; i < count; i++)
    {
        uint8_t uart_id = cfgs[i].uart_id;
        if (uart_id >= NVS_UART_MAX)
            continue;

        xSemaphoreTake(resource_mutex, portMAX_DELAY);
        uart_table[uart_id].baudrate = cfgs[i].baudrate;
        uart_table[uart_id].data_bits = cfgs[i].data_bits;
        uart_table[uart_id].parity = cfgs[i].parity;
        uart_table[uart_id].stop_bits = cfgs[i].stop_bits;
        uart_table[uart_id].tx_pin = cfgs[i].tx_gpio;
        uart_table[uart_id].rx_pin = cfgs[i].rx_gpio;
        uart_table[uart_id].in_use = cfgs[i].in_use;
        uart_table[uart_id].owner = 0;
        xSemaphoreGive(resource_mutex);

        if (cfgs[i].tx_gpio < 31)
        {
            gpio_table[cfgs[i].tx_gpio].owner = uart_id;
            gpio_table[cfgs[i].tx_gpio].in_use = 1;
        }
        if (cfgs[i].rx_gpio < 31)
        {
            gpio_table[cfgs[i].rx_gpio].owner = uart_id;
            gpio_table[cfgs[i].rx_gpio].in_use = 1;
        }

        uart_config_t uart_config = {
            .baud_rate = cfgs[i].baudrate,
            .data_bits = nvs_map_data_bits(cfgs[i].data_bits),
            .parity = nvs_map_parity(cfgs[i].parity),
            .stop_bits = nvs_map_stop_bits(cfgs[i].stop_bits),
            .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        };

        if (uart_param_config(uart_id, &uart_config) == ESP_OK &&
            uart_set_pin(uart_id, cfgs[i].tx_gpio, cfgs[i].rx_gpio,
                         UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE) == ESP_OK)
        {
            QueueHandle_t uart_event_queue = NULL;
            if (uart_driver_install(uart_id, 1024, 1024, 16, &uart_event_queue, 0) == ESP_OK)
            {
                uart_table[uart_id].event_queue = uart_event_queue;
            }
        }

        restored++;
        ESP_LOGI(TAG, "Restored UART%d baud=%lu tx=%d rx=%d",
                 uart_id, (unsigned long)cfgs[i].baudrate,
                 cfgs[i].tx_gpio, cfgs[i].rx_gpio);
    }

    free(blob);
    return restored;
}

void nvs_restore_uart_all(void)
{
    nvs_handle_t handle;
    if (nvs_open(NVS_CFG_NS, NVS_READONLY, &handle) != ESP_OK)
    {
        ESP_LOGI(TAG, "No UART config in NVS");
        return;
    }
    int n = _nvs_restore_uart(handle);
    nvs_close(handle);
    ESP_LOGI(TAG, "UART restore complete: %d ports", n);
}

// ── BLE persistence ───────────────────────────────────────────

void nvs_save_ble(void)
{
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_CFG_NS, NVS_READWRITE, &handle);
    if (err != ESP_OK)
    {
        ESP_LOGW(TAG, "nvs_open ble failed: %d", err);
        return;
    }
    _nvs_save_ble_keys(handle);
    err = nvs_commit(handle);
    nvs_close(handle);
    if (err == ESP_OK)
    {
        ESP_LOGI(TAG, "BLE config saved (scan=%d, interval=%lu)",
                 ble_rssi_scan_enabled, (unsigned long)ble_rssi_interval_s);
    }
    else
    {
        ESP_LOGW(TAG, "BLE config save failed: %d", err);
    }
}

// ── Internal BLE restore ──────────────────────────────────────

static void _nvs_restore_ble(nvs_handle_t handle)
{
    uint8_t scan_en = 0;
    uint32_t scan_int = 5;

    nvs_get_u8(handle, KEY_BLE_SCAN_EN, &scan_en);
    nvs_get_u32(handle, KEY_BLE_SCAN_INT, &scan_int);

    ble_rssi_scan_enabled = scan_en;
    ble_rssi_interval_s = (scan_int > 0) ? scan_int : 5;

    ESP_LOGI(TAG, "BLE config restored: scan_en=%d interval=%lu",
             ble_rssi_scan_enabled, (unsigned long)ble_rssi_interval_s);
}

void nvs_restore_ble(void)
{
    nvs_handle_t handle;
    if (nvs_open(NVS_CFG_NS, NVS_READONLY, &handle) != ESP_OK)
    {
        ESP_LOGI(TAG, "No BLE config in NVS");
        return;
    }
    _nvs_restore_ble(handle);
    nvs_close(handle);
}

// ── Aggregate save (one NVS transaction) ─────────────────────

void nvs_save_all(uint32_t session_version)
{
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_CFG_NS, NVS_READWRITE, &handle);
    if (err != ESP_OK)
    {
        ESP_LOGW(TAG, "nvs_save_all: open failed %d", err);
        return;
    }

    int gpio_n = 0, uart_n = 0;
    _nvs_save_gpio_blob(handle, &gpio_n);
    _nvs_save_uart_blob(handle, &uart_n);
    _nvs_save_ble_keys(handle);
    nvs_set_u32(handle, KEY_SESSION_VER, session_version);

    err = nvs_commit(handle);
    nvs_close(handle);

    if (err == ESP_OK)
    {
        ESP_LOGI(TAG, "All configs saved (gpio=%d, uart=%d, ble, session=%lu)",
                 gpio_n, uart_n, (unsigned long)session_version);
    }
    else
    {
        ESP_LOGW(TAG, "nvs_save_all commit failed: %d", err);
    }
}

// ── Aggregate restore (opens NVS once) ───────────────────────

void nvs_restore_all(void)
{
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_CFG_NS, NVS_READONLY, &handle);
    if (err != ESP_OK)
    {
        ESP_LOGI(TAG, "No NVS config namespace (first boot or erased)");
        return;
    }

    ESP_LOGI(TAG, "=== Restoring persistent configs from NVS ===");
    int gpio_n = _nvs_restore_gpio(handle);
    int uart_n = _nvs_restore_uart(handle);
    _nvs_restore_ble(handle);
    nvs_close(handle);
    ESP_LOGI(TAG, "=== Restore complete: %d gpio, %d uart, + ble ===", gpio_n, uart_n);
}
