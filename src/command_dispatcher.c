#include "iot_agent.h"
#include "nvs_store.h"
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "driver/gpio.h"
#include "driver/uart.h"
#include "driver/adc.h"
#include "esp_timer.h"
#include <stdlib.h>

static const char *TAG = "dispatcher";
#define MAX_PENDING_SYNC 32

typedef struct
{
    uint16_t cmd_id;
    uint8_t status;
    uint8_t error_code;
    uint32_t correlation_id;
} pending_cmd_ack_t;

typedef struct
{
    uint16_t device_id;
    uint16_t payload_len;
    uint32_t correlation_id;
    uint8_t *payload;
} pending_thread_result_t;

static pending_cmd_ack_t pending_ack_events[MAX_PENDING_SYNC] = {0};
static int pending_ack_count = 0;
static pending_thread_result_t pending_thread_results[MAX_PENDING_SYNC] = {0};
static int pending_thread_count = 0;
static uint32_t session_version = 0;

static void store_pending_ack(uint16_t cmd_id, uint8_t status, uint8_t error_code, uint32_t correlation_id)
{
    if (correlation_id == 0 || pending_ack_count >= MAX_PENDING_SYNC)
    {
        return;
    }
    for (int i = 0; i < pending_ack_count; i++)
    {
        if (pending_ack_events[i].correlation_id == correlation_id)
        {
            return;
        }
    }
    pending_ack_events[pending_ack_count].cmd_id = cmd_id;
    pending_ack_events[pending_ack_count].status = status;
    pending_ack_events[pending_ack_count].error_code = error_code;
    pending_ack_events[pending_ack_count].correlation_id = correlation_id;
    pending_ack_count++;
}

static void clear_pending_ack(uint32_t correlation_id)
{
    if (correlation_id == 0)
    {
        return;
    }
    for (int i = 0; i < pending_ack_count; i++)
    {
        if (pending_ack_events[i].correlation_id == correlation_id)
        {
            for (int j = i; j < pending_ack_count - 1; j++)
            {
                pending_ack_events[j] = pending_ack_events[j + 1];
            }
            pending_ack_count--;
            return;
        }
    }
}

static void store_pending_thread_result(uint16_t device_id, uint16_t payload_len, uint32_t correlation_id, uint8_t *payload)
{
    if (correlation_id == 0 || pending_thread_count >= MAX_PENDING_SYNC)
    {
        return;
    }
    for (int i = 0; i < pending_thread_count; i++)
    {
        if (pending_thread_results[i].correlation_id == correlation_id)
        {
            return;
        }
    }

    uint8_t *copy = (uint8_t *)malloc(payload_len);
    if (!copy)
    {
        return;
    }
    memcpy(copy, payload, payload_len);
    pending_thread_results[pending_thread_count].device_id = device_id;
    pending_thread_results[pending_thread_count].payload_len = payload_len;
    pending_thread_results[pending_thread_count].correlation_id = correlation_id;
    pending_thread_results[pending_thread_count].payload = copy;
    pending_thread_count++;
}

static void clear_pending_thread_result(uint32_t correlation_id)
{
    if (correlation_id == 0)
    {
        return;
    }
    for (int i = 0; i < pending_thread_count; i++)
    {
        if (pending_thread_results[i].correlation_id == correlation_id)
        {
            free(pending_thread_results[i].payload);
            for (int j = i; j < pending_thread_count - 1; j++)
            {
                pending_thread_results[j] = pending_thread_results[j + 1];
            }
            pending_thread_count--;
            return;
        }
    }
}

static bool resend_pending_items_for_correlation(uint32_t correlation_id)
{
    bool resent = false;
    if (correlation_id == 0)
    {
        return false;
    }
    for (int i = 0; i < pending_ack_count; i++)
    {
        if (pending_ack_events[i].correlation_id == correlation_id)
        {
            send_event(EVENT_CMD_ACK, &pending_ack_events[i], sizeof(event_cmd_ack_t));
            resent = true;
            break;
        }
    }
    for (int i = 0; i < pending_thread_count; i++)
    {
        if (pending_thread_results[i].correlation_id == correlation_id)
        {
            size_t response_size = sizeof(event_thread_response_t) + pending_thread_results[i].payload_len;
            uint8_t *buffer = (uint8_t *)malloc(response_size);
            if (buffer)
            {
                event_thread_response_t *evt = (event_thread_response_t *)buffer;
                evt->device_id = pending_thread_results[i].device_id;
                evt->payload_len = pending_thread_results[i].payload_len;
                evt->correlation_id = pending_thread_results[i].correlation_id;
                evt->timestamp_us = esp_timer_get_time();
                memcpy(buffer + sizeof(event_thread_response_t), pending_thread_results[i].payload,
                       pending_thread_results[i].payload_len);
                send_event(EVENT_THREAD_RESPONSE, buffer, response_size);
                free(buffer);
            }
            resent = true;
        }
    }
    return resent;
}

static void send_pending_sync_snapshot(void)
{
    uint16_t port_status_count = 0;
    for (int i = 0; i < 31; i++)
    {
        if (gpio_table[i].in_use)
        {
            port_status_count++;
        }
    }
    for (int i = 0; i < IOT_UART_NUM_MAX; i++)
    {
        if (uart_table[i].in_use)
        {
            port_status_count++;
        }
    }

    event_sync_response_t sync_event = {
        .session_version = session_version,
        .pending_cmd_count = (uint16_t)pending_ack_count,
        .pending_thread_count = (uint16_t)pending_thread_count,
        .port_status_count = port_status_count};
    send_event(EVENT_SYNC_RESPONSE, &sync_event, sizeof(event_sync_response_t));

    // Re-send pending command ACKs and pending Thread results.
    for (int i = 0; i < pending_ack_count; i++)
    {
        send_event(EVENT_CMD_ACK, &pending_ack_events[i], sizeof(event_cmd_ack_t));
    }
    for (int i = 0; i < pending_thread_count; i++)
    {
        size_t response_size = sizeof(event_thread_response_t) + pending_thread_results[i].payload_len;
        uint8_t *buffer = (uint8_t *)malloc(response_size);
        if (!buffer)
        {
            continue;
        }
        event_thread_response_t *evt = (event_thread_response_t *)buffer;
        evt->device_id = pending_thread_results[i].device_id;
        evt->payload_len = pending_thread_results[i].payload_len;
        evt->correlation_id = pending_thread_results[i].correlation_id;
        evt->timestamp_us = esp_timer_get_time();
        memcpy(buffer + sizeof(event_thread_response_t), pending_thread_results[i].payload, pending_thread_results[i].payload_len);
        send_event(EVENT_THREAD_RESPONSE, buffer, response_size);
        free(buffer);
    }

    // Send current port status snapshot for bound resources.
    for (int i = 0; i < 31; i++)
    {
        if (gpio_table[i].in_use)
        {
            event_port_status_t status = {
                .resource_type = 0,
                .id = (uint8_t)i,
                .mode = gpio_table[i].mode,
                .owner = gpio_table[i].owner,
                .in_use = gpio_table[i].in_use,
                .value = gpio_table[i].value};
            send_event(EVENT_PORT_STATUS, &status, sizeof(event_port_status_t));

            // Full GPIO state
            event_gpio_status_t full = {
                .gpio = (uint8_t)i,
                .mode = gpio_table[i].mode,
                .pull = gpio_table[i].pull,
                .edge = gpio_table[i].edge,
                .value = gpio_table[i].value,
                .in_use = gpio_table[i].in_use,
                .owner = gpio_table[i].owner,
                .adc_raw = gpio_table[i].adc_value,
                .adc_mv = gpio_table[i].adc_voltage_mv,
            };
            send_event(EVENT_GPIO_STATUS, &full, sizeof(event_gpio_status_t));
        }
    }
    for (int i = 0; i < IOT_UART_NUM_MAX; i++)
    {
        if (uart_table[i].in_use)
        {
            // Legacy port_status for backward compat
            event_port_status_t status = {
                .resource_type = 1,
                .id = (uint8_t)i,
                .mode = 0,
                .owner = uart_table[i].owner,
                .in_use = uart_table[i].in_use,
                .value = (uint8_t)(uart_table[i].baudrate & 0xFF)};
            send_event(EVENT_PORT_STATUS, &status, sizeof(event_port_status_t));

            // Full UART state
            event_uart_status_t full = {
                .uart_id = (uint8_t)i,
                .baudrate = uart_table[i].baudrate,
                .data_bits = uart_table[i].data_bits,
                .parity = uart_table[i].parity,
                .stop_bits = uart_table[i].stop_bits,
                .tx_gpio = uart_table[i].tx_pin,
                .rx_gpio = uart_table[i].rx_pin,
                .in_use = uart_table[i].in_use,
                .owner = uart_table[i].owner,
            };
            send_event(EVENT_UART_STATUS, &full, sizeof(event_uart_status_t));
        }
    }

    // Send BLE status
    {
        uint8_t peer_count = (uint8_t)ble_encrypted_peer_count();
        event_ble_status_t ble_status = {
            .pairing_enabled = ble_pairing_enabled,
            .scan_enabled = ble_rssi_scan_enabled,
            .peer_count = peer_count,
            .pairing_timeout_s = ble_pairing_timeout_s,
        };
        send_event(EVENT_BLE_STATUS, &ble_status, sizeof(event_ble_status_t));
    }
}

static void send_cmd_ack(uint16_t cmd_id, uint8_t status, uint8_t error_code, uint32_t correlation_id)
{
    event_cmd_ack_t ack = {
        .cmd_id = cmd_id,
        .status = status,
        .error_code = error_code,
        .correlation_id = correlation_id};
    send_event(EVENT_CMD_ACK, &ack, sizeof(event_cmd_ack_t));
    if (correlation_id != 0)
    {
        store_pending_ack(cmd_id, status, error_code, correlation_id);
    }
}

void init_sync_state(void)
{
    session_version = nvs_load_session_version() + 1;
    nvs_save_session_version(session_version);
}

static uart_word_length_t map_data_bits(uint8_t data_bits)
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
        return UART_DATA_8_BITS;
    default:
        return UART_DATA_8_BITS;
    }
}

static uart_parity_t map_parity(uint8_t parity)
{
    switch (parity)
    {
    case 0:
        return UART_PARITY_DISABLE;
    case 1:
        return UART_PARITY_EVEN;
    case 2:
        return UART_PARITY_ODD;
    default:
        return UART_PARITY_DISABLE;
    }
}

static uart_stop_bits_t map_stop_bits(uint8_t stop_bits)
{
    switch (stop_bits)
    {
    case 1:
        return UART_STOP_BITS_1;
    case 2:
        return UART_STOP_BITS_2;
    default:
        return UART_STOP_BITS_1;
    }
}

// Command Dispatcher Task
void command_dispatcher_task(void *pvParameters)
{
    msg_frame_t *frame;
    while (1)
    {
        if (xQueueReceive(cmd_queue, &frame, portMAX_DELAY) == pdTRUE)
        {
            handle_command(frame);
            free(frame);
        }
    }
}

// Handle Command
void handle_command(msg_frame_t *frame)
{
    uint8_t opcode = frame->payload[0];
    uint16_t cmd_id = frame->cmd_id;

    switch (opcode)
    {
    case CMD_GPIO_CONFIG:
    {
        cmd_gpio_config_t *cmd = (cmd_gpio_config_t *)&frame->payload[1];
        if (cmd->gpio >= 31)
        {
            send_event(EVENT_ERROR, &(event_cmd_ack_t){cmd_id, 1, 1, 0}, sizeof(event_cmd_ack_t));
            break;
        }
        xSemaphoreTake(resource_mutex, portMAX_DELAY);
        gpio_table[cmd->gpio].mode = cmd->mode;
        gpio_table[cmd->gpio].pull = cmd->pull;
        gpio_table[cmd->gpio].edge = cmd->edge;
        gpio_table[cmd->gpio].in_use = 1;
        gpio_table[cmd->gpio].owner = 0;
        xSemaphoreGive(resource_mutex);

        gpio_config_t io_conf = {};
        io_conf.intr_type = GPIO_INTR_DISABLE;

        switch (cmd->mode)
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
        }

        io_conf.pin_bit_mask = (1ULL << cmd->gpio);
        io_conf.pull_down_en = cmd->pull == 1 ? GPIO_PULLDOWN_ENABLE : GPIO_PULLDOWN_DISABLE;
        io_conf.pull_up_en = cmd->pull == 2 ? GPIO_PULLUP_ENABLE : GPIO_PULLUP_DISABLE;
        gpio_config(&io_conf);

        if (cmd->mode == IOT_GPIO_MODE_INTERRUPT)
        {
            gpio_install_isr_service(0);
            gpio_isr_handler_add(cmd->gpio, gpio_isr_handler, (void *)(uintptr_t)cmd->gpio);
        }

        nvs_save_gpio_all();

        send_event(EVENT_CMD_ACK, &(event_cmd_ack_t){cmd_id, 0, 0, 0}, sizeof(event_cmd_ack_t));
        break;
    }

    case CMD_GPIO_SET:
    {
        cmd_gpio_set_t *cmd = (cmd_gpio_set_t *)&frame->payload[1];
        if (cmd->gpio >= 31 || gpio_table[cmd->gpio].mode != IOT_GPIO_MODE_OUTPUT)
        {
            send_event(EVENT_ERROR, &(event_cmd_ack_t){cmd_id, 1, 2, 0}, sizeof(event_cmd_ack_t));
            break;
        }
        gpio_set_level(cmd->gpio, cmd->value);
        gpio_table[cmd->gpio].value = cmd->value;
        gpio_table[cmd->gpio].last_ts = esp_timer_get_time();
        nvs_save_gpio_all();
        send_event(EVENT_CMD_ACK, &(event_cmd_ack_t){cmd_id, 0, 0, 0}, sizeof(event_cmd_ack_t));
        break;
    }

    case CMD_GPIO_GET:
    {
        cmd_gpio_get_t *cmd = (cmd_gpio_get_t *)&frame->payload[1];
        if (cmd->gpio >= 31)
        {
            send_event(EVENT_ERROR, &(event_cmd_ack_t){cmd_id, 1, 1, 0}, sizeof(event_cmd_ack_t));
            break;
        }
        uint8_t value = gpio_get_level(cmd->gpio);
        gpio_table[cmd->gpio].value = value;
        gpio_table[cmd->gpio].last_ts = esp_timer_get_time();
        event_gpio_value_t event = {cmd->gpio, value, esp_timer_get_time()};
        send_event(EVENT_GPIO_VALUE, &event, sizeof(event_gpio_value_t));
        break;
    }

    case CMD_ADC_SAMPLE:
    {
        cmd_adc_sample_t *cmd = (cmd_adc_sample_t *)&frame->payload[1];
        if (cmd->gpio >= 31)
        {
            send_event(EVENT_ERROR, &(event_cmd_ack_t){cmd_id, 1, 1, 0}, sizeof(event_cmd_ack_t));
            break;
        }
        uint16_t value = adc_read_sample(cmd->gpio, cmd->samples);
        gpio_table[cmd->gpio].adc_value = value;
        gpio_table[cmd->gpio].adc_voltage_mv = (uint16_t)(value * 3300 / 4095);
        event_adc_value_t event = {cmd->gpio, value, esp_timer_get_time()};
        send_event(EVENT_ADC_VALUE, &event, sizeof(event_adc_value_t));
        break;
    }

    case CMD_GPIO_SIGNAL_TX:
    {
        cmd_gpio_signal_tx_t *cmd = (cmd_gpio_signal_tx_t *)&frame->payload[1];
        if (cmd->gpio >= 31 || gpio_table[cmd->gpio].mode != IOT_GPIO_MODE_SIGNAL)
        {
            send_event(EVENT_ERROR, &(event_cmd_ack_t){cmd_id, 1, IOT_ERR_INVALID_STATE, 0}, sizeof(event_cmd_ack_t));
            break;
        }

        // Empty signal is a valid no-op
        if (cmd->signal_len == 0)
        {
            send_event(EVENT_CMD_ACK, &(event_cmd_ack_t){cmd_id, 0, 0}, sizeof(event_cmd_ack_t));
            break;
        }

        size_t signal_data_size = cmd->signal_len * 5; // 1 byte level + 4 bytes duration
        uint8_t *signal_data = (uint8_t *)malloc(signal_data_size);
        if (!signal_data)
        {
            send_event(EVENT_ERROR, &(event_cmd_ack_t){cmd_id, 1, IOT_ERR_UNSUPPORTED, 0}, sizeof(event_cmd_ack_t));
            break;
        }

        uint8_t *payload_ptr = (uint8_t *)cmd + sizeof(cmd_gpio_signal_tx_t);
        memcpy(signal_data, payload_ptr, signal_data_size);

        gpio_signal_tx_item_t tx_item = {
            .cmd_id = cmd_id,
            .gpio = cmd->gpio,
            .signal_len = cmd->signal_len,
            .delay_us = cmd->delay_us,
            .signal_data = signal_data,
            .tx_channel = -1,
            .rx_channel = -1,
            .do_rx = 0};

        if (xQueueSend(get_signal_tx_queue(), &tx_item, pdMS_TO_TICKS(100)) != pdTRUE)
        {
            ESP_LOGW(TAG, "Signal TX queue full");
            send_event(EVENT_ERROR, &(event_cmd_ack_t){cmd_id, 1, IOT_ERR_RESOURCE_EXHAUSTED, 0}, sizeof(event_cmd_ack_t));
            free(signal_data);
        }
        break;
    }

    case CMD_GPIO_SIGNAL_EXCHANGE:
    {
        cmd_gpio_signal_exchange_t *cmd = (cmd_gpio_signal_exchange_t *)&frame->payload[1];
        if (cmd->gpio >= 31 || gpio_table[cmd->gpio].mode != IOT_GPIO_MODE_SIGNAL)
        {
            send_event(EVENT_ERROR, &(event_cmd_ack_t){cmd_id, 1, IOT_ERR_INVALID_STATE, 0}, sizeof(event_cmd_ack_t));
            break;
        }

        // Extract tx data (NULL for empty tx)
        uint8_t *signal_data = NULL;
        if (cmd->tx_len > 0)
        {
            size_t tx_data_size = cmd->tx_len * 5;
            signal_data = (uint8_t *)malloc(tx_data_size);
            if (!signal_data)
            {
                send_event(EVENT_ERROR, &(event_cmd_ack_t){cmd_id, 1, IOT_ERR_UNSUPPORTED, 0}, sizeof(event_cmd_ack_t));
                break;
            }
            uint8_t *payload_ptr = (uint8_t *)cmd + sizeof(cmd_gpio_signal_exchange_t);
            memcpy(signal_data, payload_ptr, tx_data_size);
        }

        gpio_signal_tx_item_t tx_item = {
            .cmd_id = cmd_id,
            .gpio = cmd->gpio,
            .signal_len = cmd->tx_len,
            .delay_us = cmd->delay_us,
            .signal_data = signal_data,
            .tx_channel = -1,
            .rx_channel = -1,
            .do_rx = 1,
            .rx_total_us = cmd->rx_total_us,
            .rx_max_edges = cmd->rx_max_edges};

        if (xQueueSend(get_signal_tx_queue(), &tx_item, pdMS_TO_TICKS(100)) != pdTRUE)
        {
            ESP_LOGW(TAG, "Signal TX queue full");
            send_event(EVENT_ERROR, &(event_cmd_ack_t){cmd_id, 1, IOT_ERR_RESOURCE_EXHAUSTED, 0}, sizeof(event_cmd_ack_t));
            free(signal_data);
        }
        break;
    }

    case CMD_GPIO_SIGNAL_RX:
    {
        cmd_gpio_signal_rx_t *cmd = (cmd_gpio_signal_rx_t *)&frame->payload[1];
        if (cmd->gpio >= 31 || gpio_table[cmd->gpio].mode != IOT_GPIO_MODE_SIGNAL)
        {
            send_event(EVENT_ERROR, &(event_cmd_ack_t){cmd_id, 1, IOT_ERR_INVALID_STATE, 0}, sizeof(event_cmd_ack_t));
            break;
        }

        // Queue RX item to dedicated task
        gpio_signal_rx_item_t rx_item = {
            .cmd_id = cmd_id,
            .gpio = cmd->gpio,
            .timeout_us = cmd->timeout_us,
            .max_edges = cmd->max_edges,
            .rx_channel = -1};

        if (xQueueSend(get_signal_rx_queue(), &rx_item, pdMS_TO_TICKS(100)) != pdTRUE)
        {
            ESP_LOGW(TAG, "Signal RX queue full");
            send_event(EVENT_ERROR, &(event_cmd_ack_t){cmd_id, 1, IOT_ERR_RESOURCE_EXHAUSTED, 0}, sizeof(event_cmd_ack_t));
        }
        // ACK will be sent by RX task after capture complete
        break;
    }

    case CMD_UART_CONFIG:
    {
        cmd_uart_config_t *cmd = (cmd_uart_config_t *)&frame->payload[1];
        if (cmd->uart_id >= IOT_UART_NUM_MAX)
        {
            send_event(EVENT_ERROR, &(event_cmd_ack_t){cmd_id, 1, 5, 0}, sizeof(event_cmd_ack_t));
            break;
        }

        if (cmd->data_bits < 5 || cmd->data_bits > 8)
        {
            send_event(EVENT_ERROR, &(event_cmd_ack_t){cmd_id, 1, 5, 0}, sizeof(event_cmd_ack_t));
            break;
        }

        xSemaphoreTake(resource_mutex, portMAX_DELAY);

        // ── Clear old GPIO ownership if reassigning ──
        uint8_t old_tx = uart_table[cmd->uart_id].tx_pin;
        uint8_t old_rx = uart_table[cmd->uart_id].rx_pin;
        if (old_tx < 31 && gpio_table[old_tx].owner == cmd->uart_id)
        {
            gpio_table[old_tx].owner = 0;
            gpio_table[old_tx].in_use = 0;
        }
        if (old_rx < 31 && gpio_table[old_rx].owner == cmd->uart_id)
        {
            gpio_table[old_rx].owner = 0;
            gpio_table[old_rx].in_use = 0;
        }

        // ── Mark new GPIO ownership ──
        if (cmd->tx_gpio < 31)
        {
            gpio_table[cmd->tx_gpio].owner = cmd->uart_id;
            gpio_table[cmd->tx_gpio].in_use = 1;
        }
        if (cmd->rx_gpio < 31)
        {
            gpio_table[cmd->rx_gpio].owner = cmd->uart_id;
            gpio_table[cmd->rx_gpio].in_use = 1;
        }

        uart_table[cmd->uart_id].tx_pin = cmd->tx_gpio;
        uart_table[cmd->uart_id].rx_pin = cmd->rx_gpio;
        uart_table[cmd->uart_id].baudrate = cmd->baudrate;
        uart_table[cmd->uart_id].data_bits = cmd->data_bits;
        uart_table[cmd->uart_id].parity = cmd->parity;
        uart_table[cmd->uart_id].stop_bits = cmd->stop_bits;
        uart_table[cmd->uart_id].in_use = 1;
        uart_table[cmd->uart_id].owner = 0;
        xSemaphoreGive(resource_mutex);

        if (uart_table[cmd->uart_id].event_queue != NULL)
        {
            uart_table[cmd->uart_id].event_queue = NULL;
        }
        uart_driver_delete(cmd->uart_id);

        uart_config_t uart_config = {
            .baud_rate = cmd->baudrate,
            .data_bits = map_data_bits(cmd->data_bits),
            .parity = map_parity(cmd->parity),
            .stop_bits = map_stop_bits(cmd->stop_bits),
            .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        };

        if (uart_param_config(cmd->uart_id, &uart_config) != ESP_OK)
        {
            send_event(EVENT_ERROR, &(event_cmd_ack_t){cmd_id, 1, 3, 0}, sizeof(event_cmd_ack_t));
            break;
        }
        if (uart_set_pin(cmd->uart_id, cmd->tx_gpio, cmd->rx_gpio, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE) != ESP_OK)
        {
            send_event(EVENT_ERROR, &(event_cmd_ack_t){cmd_id, 1, 3, 0}, sizeof(event_cmd_ack_t));
            break;
        }
        QueueHandle_t uart_event_queue = NULL;
        if (uart_driver_install(cmd->uart_id, 1024, 1024, 16, &uart_event_queue, 0) != ESP_OK)
        {
            send_event(EVENT_ERROR, &(event_cmd_ack_t){cmd_id, 1, 3, 0}, sizeof(event_cmd_ack_t));
            break;
        }

        xSemaphoreTake(resource_mutex, portMAX_DELAY);
        uart_table[cmd->uart_id].event_queue = uart_event_queue;
        xSemaphoreGive(resource_mutex);

        nvs_save_uart_all();

        send_event(EVENT_CMD_ACK, &(event_cmd_ack_t){cmd_id, 0, 0, 0}, sizeof(event_cmd_ack_t));
        break;
    }

    case CMD_UART_SEND:
    {
        cmd_uart_send_t *cmd = (cmd_uart_send_t *)&frame->payload[1];
        if (cmd->uart_id >= IOT_UART_NUM_MAX || !uart_table[cmd->uart_id].in_use)
        {
            send_event(EVENT_ERROR, &(event_cmd_ack_t){cmd_id, 1, 5, 0}, sizeof(event_cmd_ack_t));
            break;
        }
        int written = uart_write_bytes(cmd->uart_id, (const char *)cmd->data, cmd->length);
        if (written != cmd->length)
        {
            send_event(EVENT_ERROR, &(event_cmd_ack_t){cmd_id, 1, 3, 0}, sizeof(event_cmd_ack_t));
        }
        else
        {
            send_event(EVENT_CMD_ACK, &(event_cmd_ack_t){cmd_id, 0, 0, 0}, sizeof(event_cmd_ack_t));
        }
        break;
    }

    case CMD_UART_READ:
    {
        cmd_uart_read_t *cmd = (cmd_uart_read_t *)&frame->payload[1];
        if (cmd->uart_id >= IOT_UART_NUM_MAX || !uart_table[cmd->uart_id].in_use)
        {
            send_event(EVENT_ERROR, &(event_cmd_ack_t){cmd_id, 1, 5, 0}, sizeof(event_cmd_ack_t));
            break;
        }

        uint16_t read_len = cmd->length;
        if (read_len > 256)
        {
            read_len = 256;
        }

        uint8_t rx_buf[256] = {0};
        int available = uart_read_bytes(cmd->uart_id, rx_buf, read_len, pdMS_TO_TICKS(50));
        if (available < 0)
        {
            send_event(EVENT_ERROR, &(event_cmd_ack_t){cmd_id, 1, 3, 0}, sizeof(event_cmd_ack_t));
            break;
        }

        size_t event_size = sizeof(event_uart_rx_t) + (size_t)available;
        uint8_t *event_buf = (uint8_t *)malloc(event_size);
        if (!event_buf)
        {
            send_event(EVENT_ERROR, &(event_cmd_ack_t){cmd_id, 1, 5, 0}, sizeof(event_cmd_ack_t));
            break;
        }

        event_uart_rx_t *event = (event_uart_rx_t *)event_buf;
        event->uart_id = cmd->uart_id;
        event->length = (uint16_t)available;
        event->timestamp_us = esp_timer_get_time();

        if (available > 0)
        {
            memcpy(&event_buf[sizeof(event_uart_rx_t)], rx_buf, (size_t)available);
        }

        send_event(EVENT_UART_RX, event_buf, event_size);
        free(event_buf);
        break;
    }

    case CMD_PORT_BIND:
    {
        cmd_port_bind_t *cmd = (cmd_port_bind_t *)&frame->payload[1];
        xSemaphoreTake(resource_mutex, portMAX_DELAY);
        if (cmd->resource_type == 0)
        { // GPIO
            if (cmd->id < 31 && !gpio_table[cmd->id].in_use)
            {
                gpio_table[cmd->id].owner = cmd->owner_id;
                gpio_table[cmd->id].in_use = 1;
                xSemaphoreGive(resource_mutex);
                send_event(EVENT_CMD_ACK, &(event_cmd_ack_t){cmd_id, 0, 0, 0}, sizeof(event_cmd_ack_t));
                break;
            }
        }
        else if (cmd->resource_type == 1)
        { // UART
            if (cmd->id < IOT_UART_NUM_MAX && !uart_table[cmd->id].in_use)
            {
                uart_table[cmd->id].owner = cmd->owner_id;
                uart_table[cmd->id].in_use = 1;
                xSemaphoreGive(resource_mutex);
                send_event(EVENT_CMD_ACK, &(event_cmd_ack_t){cmd_id, 0, 0, 0}, sizeof(event_cmd_ack_t));
                break;
            }
        }
        xSemaphoreGive(resource_mutex);
        send_event(EVENT_ERROR, &(event_cmd_ack_t){cmd_id, 1, 4, 0}, sizeof(event_cmd_ack_t));
        break;
    }

    case CMD_PORT_UNBIND:
    {
        cmd_port_status_t *cmd = (cmd_port_status_t *)&frame->payload[1];
        xSemaphoreTake(resource_mutex, portMAX_DELAY);
        if (cmd->resource_type == 0)
        { // GPIO
            if (cmd->id < 31 && gpio_table[cmd->id].in_use)
            {
                uint8_t prev_mode = gpio_table[cmd->id].mode;
                gpio_table[cmd->id].in_use = 0;
                gpio_table[cmd->id].owner = 0;
                // Optionally reset mode and value
                gpio_table[cmd->id].mode = 0xFF;
                gpio_table[cmd->id].value = 0;
                gpio_table[cmd->id].last_ts = 0;
                xSemaphoreGive(resource_mutex);

                // Release actual pin state so later tests (e.g., UART on GPIO3) are not electrically blocked.
                if (prev_mode == IOT_GPIO_MODE_INTERRUPT)
                {
                    gpio_isr_handler_remove(cmd->id);
                }
                gpio_reset_pin(cmd->id);

                nvs_save_gpio_all();

                send_event(EVENT_CMD_ACK, &(event_cmd_ack_t){cmd_id, 0, 0, 0}, sizeof(event_cmd_ack_t));
                break;
            }
        }
        else if (cmd->resource_type == 1)
        { // UART
            if (cmd->id < IOT_UART_NUM_MAX && uart_table[cmd->id].in_use)
            {
                QueueHandle_t old_queue = uart_table[cmd->id].event_queue;
                uart_table[cmd->id].in_use = 0;
                uart_table[cmd->id].owner = 0;
                // Optionally reset UART config
                uart_table[cmd->id].tx_pin = 0xFF;
                uart_table[cmd->id].rx_pin = 0xFF;
                uart_table[cmd->id].baudrate = 0;
                uart_table[cmd->id].event_queue = NULL;
                xSemaphoreGive(resource_mutex);

                if (old_queue != NULL)
                {
                    uart_flush_input(cmd->id);
                }
                uart_driver_delete(cmd->id);

                nvs_save_uart_all();

                send_event(EVENT_CMD_ACK, &(event_cmd_ack_t){cmd_id, 0, 0, 0}, sizeof(event_cmd_ack_t));
                break;
            }
        }
        xSemaphoreGive(resource_mutex);
        send_event(EVENT_ERROR, &(event_cmd_ack_t){cmd_id, 1, 4, 0}, sizeof(event_cmd_ack_t));
        break;
    }

    case CMD_PORT_STATUS:
    {
        cmd_port_status_t *cmd = (cmd_port_status_t *)&frame->payload[1];
        event_port_status_t status = {cmd->resource_type, cmd->id, 0, 0, 0, 0};

        if (cmd->resource_type == 0 && cmd->id < 31)
        {
            status.mode = gpio_table[cmd->id].mode;
            status.owner = gpio_table[cmd->id].owner;
            status.in_use = gpio_table[cmd->id].in_use;
            status.value = gpio_table[cmd->id].value;
        }
        else if (cmd->resource_type == 1 && cmd->id < IOT_UART_NUM_MAX)
        {
            status.in_use = uart_table[cmd->id].in_use;
            status.owner = uart_table[cmd->id].owner;
            status.value = uart_table[cmd->id].baudrate & 0xFF;
        }
        send_event(EVENT_PORT_STATUS, &status, sizeof(event_port_status_t));
        break;
    }

    case CMD_THREAD_PASSTHROUGH:
    {
        cmd_thread_passthrough_t *cmd = (cmd_thread_passthrough_t *)&frame->payload[1];

        if (cmd->correlation_id != 0 && resend_pending_items_for_correlation(cmd->correlation_id))
        {
            break;
        }

        // Find device
        xSemaphoreTake(resource_mutex, portMAX_DELAY);
        int found = 0;
        for (int i = 0; i < 16; i++)
        {
            if (thread_table[i].device_id == cmd->device_id && thread_table[i].online)
            {
                found = 1;
                break;
            }
        }
        xSemaphoreGive(resource_mutex);

        if (!found)
        {
            send_event(EVENT_ERROR, &(event_cmd_ack_t){cmd_id, 1, 6, 0}, sizeof(event_cmd_ack_t));
            break;
        }

        // In real implementation, send command to Thread device
        send_cmd_ack(cmd_id, 0, 0, cmd->correlation_id);

        // Simulate response after delay
        vTaskDelay(pdMS_TO_TICKS(100));
        size_t response_size = sizeof(event_thread_response_t) + cmd->payload_len;
        uint8_t *response = (uint8_t *)malloc(response_size);
        if (response)
        {
            event_thread_response_t *evt = (event_thread_response_t *)response;
            evt->device_id = cmd->device_id;
            evt->payload_len = cmd->payload_len;
            evt->correlation_id = cmd->correlation_id;
            evt->timestamp_us = esp_timer_get_time();
            memcpy(&response[sizeof(event_thread_response_t)], cmd->payload, cmd->payload_len);
            send_event(EVENT_THREAD_RESPONSE, response, response_size);
            store_pending_thread_result(cmd->device_id, cmd->payload_len, cmd->correlation_id, cmd->payload);
            free(response);
        }
        break;
    }

    case CMD_HEARTBEAT:
    {
        cmd_heartbeat_t *cmd = (cmd_heartbeat_t *)&frame->payload[1];
        event_heartbeat_t hb = {cmd->timestamp, connection_state};
        send_event(EVENT_HEARTBEAT, &hb, sizeof(event_heartbeat_t));
        break;
    }

    case CMD_BLE_ENABLE_PAIRING:
    {
        cmd_ble_enable_pairing_t *cmd = (cmd_ble_enable_pairing_t *)&frame->payload[1];
        ble_enable_pairing(cmd->timeout_s);
        send_event(EVENT_CMD_ACK, &(event_cmd_ack_t){cmd_id, 0, 0, 0}, sizeof(event_cmd_ack_t));
        break;
    }

    case CMD_BLE_DISABLE_PAIRING:
    {
        ble_disable_pairing();
        send_event(EVENT_CMD_ACK, &(event_cmd_ack_t){cmd_id, 0, 0, 0}, sizeof(event_cmd_ack_t));
        break;
    }

    case CMD_BLE_GET_PEERS:
    {
        ble_peer_t peers_buffer[4] = {0};
        int peer_count = 4;
        ble_get_peers_list(peers_buffer, &peer_count);

        // 构建响应
        int response_size = sizeof(event_ble_peers_list_t) + (peer_count * 7);
        uint8_t *response = malloc(response_size);
        if (!response)
            break;

        event_ble_peers_list_t *evt = (event_ble_peers_list_t *)response;
        evt->peer_count = peer_count;

        uint8_t *data_ptr = response + sizeof(event_ble_peers_list_t);
        for (int i = 0; i < peer_count; i++)
        {
            memcpy(data_ptr, peers_buffer[i].peer_mac, 6);
            data_ptr[6] = (uint8_t)peers_buffer[i].rssi;
            data_ptr += 7;
        }

        send_event(EVENT_BLE_PEERS_LIST, response, response_size);
        free(response);
        break;
    }

    case CMD_BLE_START_SCAN:
    {
        cmd_ble_start_scan_t *cmd = (cmd_ble_start_scan_t *)&frame->payload[1];
        ble_start_rssi_scan(cmd->interval_s);
        send_cmd_ack(cmd_id, 0, 0, 0);
        break;
    }

    case CMD_BLE_STOP_SCAN:
    {
        ble_stop_rssi_scan();
        send_cmd_ack(cmd_id, 0, 0, 0);
        break;
    }

    case CMD_SYNC_REQUEST:
    {
        send_cmd_ack(cmd_id, 0, 0, 0);
        send_pending_sync_snapshot();
        break;
    }

    case CMD_SYN:
    {
        cmd_syn_t *cmd = (cmd_syn_t *)&frame->payload[1];
        if (cmd->stage == 0)
        {
            clear_pending_ack(cmd->correlation_id);
        }
        else if (cmd->stage == 1)
        {
            clear_pending_thread_result(cmd->correlation_id);
        }
        send_cmd_ack(cmd_id, 0, 0, 0);
        break;
    }

    case CMD_PING:
    {
        send_cmd_ack(cmd_id, 0, 0, 0);
        break;
    }

    default:
        ESP_LOGW(TAG, "Unknown command opcode: 0x%02X", opcode);
        send_event(EVENT_ERROR, &(event_cmd_ack_t){cmd_id, 1, 0xFF, 0}, sizeof(event_cmd_ack_t));
    }
}
