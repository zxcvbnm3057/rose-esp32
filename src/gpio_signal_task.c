#include "iot_agent.h"
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "driver/gpio.h"
#include "driver/rmt.h"
#include "esp_timer.h"
#include <stdlib.h>

static const char *TAG = "gpio_signal";

static QueueHandle_t gpio_signal_tx_queue = NULL;
static QueueHandle_t gpio_signal_rx_queue = NULL;
static SemaphoreHandle_t rmt_resource_mutex = NULL;
static bool rmt_tx_in_use[2] = {false, false};
static bool rmt_rx_in_use[2] = {false, false};

bool reserve_rmt_tx_channel(int8_t *channel_out)
{
    if (!rmt_resource_mutex)
    {
        rmt_resource_mutex = xSemaphoreCreateMutex();
        if (!rmt_resource_mutex)
        {
            return false;
        }
    }

    xSemaphoreTake(rmt_resource_mutex, portMAX_DELAY);
    for (int i = 0; i < 2; i++)
    {
        if (!rmt_tx_in_use[i])
        {
            rmt_tx_in_use[i] = true;
            *channel_out = (int8_t)i;
            xSemaphoreGive(rmt_resource_mutex);
            return true;
        }
    }
    xSemaphoreGive(rmt_resource_mutex);
    return false;
}

bool reserve_rmt_rx_channel(int8_t *channel_out)
{
    if (!rmt_resource_mutex)
    {
        rmt_resource_mutex = xSemaphoreCreateMutex();
        if (!rmt_resource_mutex)
        {
            return false;
        }
    }

    xSemaphoreTake(rmt_resource_mutex, portMAX_DELAY);
    for (int i = 0; i < 2; i++)
    {
        if (!rmt_rx_in_use[i])
        {
            rmt_rx_in_use[i] = true;
            *channel_out = (int8_t)(i + 2);
            xSemaphoreGive(rmt_resource_mutex);
            return true;
        }
    }
    xSemaphoreGive(rmt_resource_mutex);
    return false;
}

void release_rmt_tx_channel(int8_t channel)
{
    if (!rmt_resource_mutex || channel < 0 || channel > 1)
    {
        return;
    }
    xSemaphoreTake(rmt_resource_mutex, portMAX_DELAY);
    rmt_tx_in_use[channel] = false;
    xSemaphoreGive(rmt_resource_mutex);
}

void release_rmt_rx_channel(int8_t channel)
{
    if (!rmt_resource_mutex || channel < 2 || channel > 3)
    {
        return;
    }
    xSemaphoreTake(rmt_resource_mutex, portMAX_DELAY);
    rmt_rx_in_use[channel - 2] = false;
    xSemaphoreGive(rmt_resource_mutex);
}

static uint8_t *build_signal_capture_payload(uint8_t gpio, const signal_edge_t *edges, uint16_t edge_count, size_t *out_size)
{
    size_t payload_size = sizeof(event_gpio_signal_captured_t) + ((size_t)edge_count * 5);
    uint8_t *payload = (uint8_t *)malloc(payload_size);
    if (!payload)
    {
        return NULL;
    }

    event_gpio_signal_captured_t *evt = (event_gpio_signal_captured_t *)payload;
    evt->gpio = gpio;
    evt->edge_count = edge_count;
    evt->timestamp_us = esp_timer_get_time();

    uint8_t *ptr = payload + sizeof(event_gpio_signal_captured_t);
    for (uint16_t i = 0; i < edge_count; i++)
    {
        ptr[i * 5] = edges[i].level;
        uint32_t d = edges[i].duration_us;
        memcpy(&ptr[i * 5 + 1], &d, sizeof(uint32_t));
    }

    *out_size = payload_size;
    return payload;
}

// Initialize signals queues
void gpio_signal_init(void)
{
    gpio_signal_tx_queue = xQueueCreate(4, sizeof(gpio_signal_tx_item_t));
    gpio_signal_rx_queue = xQueueCreate(4, sizeof(gpio_signal_rx_item_t));
    if (!rmt_resource_mutex)
    {
        rmt_resource_mutex = xSemaphoreCreateMutex();
    }
}

// Get TX queue
QueueHandle_t get_signal_tx_queue(void)
{
    if (!gpio_signal_tx_queue)
    {
        gpio_signal_init();
    }
    return gpio_signal_tx_queue;
}

// Get RX queue
QueueHandle_t get_signal_rx_queue(void)
{
    if (!gpio_signal_rx_queue)
    {
        gpio_signal_init();
    }
    return gpio_signal_rx_queue;
}

// GPIO Signal TX Task - handles time-critical signal transmission
void gpio_signal_tx_task(void *pvParameters)
{
    gpio_signal_tx_item_t item;

    ESP_LOGI(TAG, "GPIO Signal TX task started");

    while (1)
    {
        if (xQueueReceive(get_signal_tx_queue(), &item, portMAX_DELAY) == pdTRUE)
        {
            ESP_LOGI(TAG, "TX: GPIO %d, signal_len %d, delay_us %d",
                     item.gpio, item.signal_len, item.delay_us);

            // Reserve channels only when command is actually executing.
            if (!reserve_rmt_tx_channel(&item.tx_channel))
            {
                event_cmd_ack_t err = {item.cmd_id, 1, IOT_ERR_RESOURCE_EXHAUSTED};
                send_event(EVENT_ERROR, &err, sizeof(event_cmd_ack_t));
                free(item.signal_data);
                continue;
            }
            if (item.do_rx)
            {
                if (!reserve_rmt_rx_channel(&item.rx_channel))
                {
                    event_cmd_ack_t err = {item.cmd_id, 1, IOT_ERR_RESOURCE_EXHAUSTED};
                    send_event(EVENT_ERROR, &err, sizeof(event_cmd_ack_t));
                    release_rmt_tx_channel(item.tx_channel);
                    free(item.signal_data);
                    continue;
                }
            }

            // Extract and execute signal sequence with RMT
            if (item.signal_data)
            {
                uint8_t *data = item.signal_data;
                int max_signal_len = item.signal_len;
                int rmt_items_len = (max_signal_len + 1) / 2;

                // Calculate needed memory blocks (48 words per block on ESP32-C6)
                int mem_blocks = (rmt_items_len + 47) / 48;
                if (mem_blocks < 1)
                    mem_blocks = 1;
                if (mem_blocks > 4)
                    mem_blocks = 4;              // Max blocks per channel (SOC_RMT_CHANNELS_PER_GROUP)
                int max_chunk = mem_blocks * 48; // Max RMT items per write

                rmt_config_t tx_config = {
                    .rmt_mode = RMT_MODE_TX,
                    .channel = item.tx_channel,
                    .gpio_num = item.gpio,
                    .clk_div = 80,
                    .mem_block_num = (uint8_t)mem_blocks,
                    .tx_config = {
                        .loop_en = false,
                        .carrier_en = false,
                        .idle_output_en = true,
                        .idle_level = RMT_IDLE_LEVEL_LOW,
                    }};

                esp_err_t tx_ret = rmt_config(&tx_config);
                if (tx_ret != ESP_OK)
                {
                    event_cmd_ack_t err = {item.cmd_id, 1, (tx_ret == ESP_ERR_NOT_FOUND) ? IOT_ERR_RESOURCE_EXHAUSTED : IOT_ERR_DRIVER};
                    send_event(EVENT_ERROR, &err, sizeof(event_cmd_ack_t));
                    release_rmt_tx_channel(item.tx_channel);
                    if (item.rx_channel >= 0)
                    {
                        release_rmt_rx_channel(item.rx_channel);
                    }
                    free(item.signal_data);
                    continue;
                }
                tx_ret = rmt_driver_install(tx_config.channel, 0, 0);
                if (tx_ret != ESP_OK)
                {
                    event_cmd_ack_t err = {item.cmd_id, 1, (tx_ret == ESP_ERR_NOT_SUPPORTED) ? IOT_ERR_UNSUPPORTED : IOT_ERR_RESOURCE_EXHAUSTED};
                    send_event(EVENT_ERROR, &err, sizeof(event_cmd_ack_t));
                    release_rmt_tx_channel(item.tx_channel);
                    if (item.rx_channel >= 0)
                    {
                        release_rmt_rx_channel(item.rx_channel);
                    }
                    free(item.signal_data);
                    continue;
                }

                // Allocate chunk buffer (sized for one max RMT write)
                rmt_item32_t *chunk_buf = calloc(max_chunk, sizeof(rmt_item32_t));
                if (!chunk_buf)
                {
                    event_cmd_ack_t err = {item.cmd_id, 1, 5};
                    send_event(EVENT_ERROR, &err, sizeof(event_cmd_ack_t));
                    rmt_driver_uninstall(tx_config.channel);
                    release_rmt_tx_channel(item.tx_channel);
                    if (item.rx_channel >= 0)
                    {
                        release_rmt_rx_channel(item.rx_channel);
                    }
                    free(item.signal_data);
                    continue;
                }

                // Transmit in chunks (each chunk ≤ max_chunk RMT items)
                int edges_sent = 0;
                bool write_failed = false;
                while (edges_sent < max_signal_len)
                {
                    int chunk_edges = max_signal_len - edges_sent;
                    int chunk_count = (chunk_edges + 1) / 2;
                    if (chunk_count > max_chunk)
                        chunk_count = max_chunk;
                    // Recalculate edges from items for this chunk
                    chunk_edges = chunk_count * 2;
                    if (chunk_edges > max_signal_len - edges_sent)
                        chunk_edges = max_signal_len - edges_sent;

                    // Build chunk_count items from signal data
                    for (int i = 0; i < chunk_count; i++)
                    {
                        int edge_idx = edges_sent + i * 2;
                        uint8_t level0 = data[edge_idx * 5];
                        uint32_t duration0 = *(uint32_t *)&data[edge_idx * 5 + 1];
                        uint8_t level1 = 0;
                        uint32_t duration1 = 0;
                        if (edge_idx + 1 < max_signal_len)
                        {
                            level1 = data[(edge_idx + 1) * 5];
                            duration1 = *(uint32_t *)&data[(edge_idx + 1) * 5 + 1];
                        }
                        chunk_buf[i].level0 = level0;
                        chunk_buf[i].duration0 = duration0;
                        chunk_buf[i].level1 = level1;
                        chunk_buf[i].duration1 = duration1;
                    }

                    esp_err_t write_ret = rmt_write_items(tx_config.channel, chunk_buf, chunk_count, true);
                    if (write_ret != ESP_OK)
                    {
                        ESP_LOGE(TAG, "rmt_write_items chunk failed: %d (count=%d)", write_ret, chunk_count);
                        write_failed = true;
                        break;
                    }
                    edges_sent += chunk_edges;
                }
                free(chunk_buf);
                rmt_wait_tx_done(tx_config.channel, pdMS_TO_TICKS(1000));
                rmt_driver_uninstall(tx_config.channel);

                if (write_failed)
                {
                    event_cmd_ack_t err = {item.cmd_id, 1, IOT_ERR_DRIVER};
                    send_event(EVENT_ERROR, &err, sizeof(event_cmd_ack_t));
                    release_rmt_tx_channel(item.tx_channel);
                    if (item.rx_channel >= 0)
                    {
                        release_rmt_rx_channel(item.rx_channel);
                    }
                    free(item.signal_data);
                    continue;
                }

                // Wait pre-RX delay if specified
                if (item.delay_us > 0)
                {
                    esp_rom_delay_us(item.delay_us);
                }

                // RX phase if requested
                if (item.do_rx)
                {
                    // 80MHz / clk_div=80 -> 1 tick = 1us
                    uint16_t filter_ticks = (item.rx_resolution_us > 0 && item.rx_resolution_us < 255)
                                                ? (uint16_t)item.rx_resolution_us
                                                : 1;
                    if (filter_ticks == 0)
                    {
                        filter_ticks = 1;
                    }
                    // End RX frame after a quiet period; avoids indefinite/empty capture behavior.
                    uint16_t idle_ticks = (item.rx_total_us > 0) ? (uint16_t)((item.rx_total_us > 60000) ? 60000 : item.rx_total_us) : 10000;

                    // Configure RX channel
                    rmt_config_t rx_config = {
                        .rmt_mode = RMT_MODE_RX,
                        .channel = item.rx_channel,
                        .gpio_num = item.gpio,
                        .clk_div = 80,
                        .mem_block_num = 1,
                        .rx_config = {
                            .filter_en = true,
                            .filter_ticks_thresh = filter_ticks,
                            .idle_threshold = idle_ticks,
                        }};
                    esp_err_t rx_ret = rmt_config(&rx_config);
                    if (rx_ret != ESP_OK)
                    {
                        event_cmd_ack_t err = {item.cmd_id, 1, (rx_ret == ESP_ERR_NOT_FOUND) ? IOT_ERR_RESOURCE_EXHAUSTED : IOT_ERR_DRIVER};
                        send_event(EVENT_ERROR, &err, sizeof(event_cmd_ack_t));
                        rmt_driver_uninstall(tx_config.channel);
                        release_rmt_tx_channel(item.tx_channel);
                        release_rmt_rx_channel(item.rx_channel);
                        free(item.signal_data);
                        continue;
                    }
                    rx_ret = rmt_driver_install(rx_config.channel, 1000, 0);
                    if (rx_ret != ESP_OK)
                    {
                        event_cmd_ack_t err = {item.cmd_id, 1, (rx_ret == ESP_ERR_NOT_SUPPORTED) ? IOT_ERR_UNSUPPORTED : IOT_ERR_RESOURCE_EXHAUSTED};
                        send_event(EVENT_ERROR, &err, sizeof(event_cmd_ack_t));
                        rmt_driver_uninstall(tx_config.channel);
                        release_rmt_tx_channel(item.tx_channel);
                        release_rmt_rx_channel(item.rx_channel);
                        free(item.signal_data);
                        continue;
                    }
                    rmt_rx_start(rx_config.channel, true);

                    RingbufHandle_t rb = NULL;
                    rmt_get_ringbuf_handle(rx_config.channel, &rb);

                    uint32_t rx_end_time = esp_timer_get_time() + item.rx_total_us;
                    int edged = 0;
                    signal_edge_t *rx_edges = malloc(sizeof(signal_edge_t) * item.rx_max_edges);
                    if (!rx_edges)
                    {
                        event_cmd_ack_t err = {item.cmd_id, 1, 5};
                        send_event(EVENT_ERROR, &err, sizeof(event_cmd_ack_t));
                        rmt_rx_stop(rx_config.channel);
                        rmt_driver_uninstall(rx_config.channel);
                        release_rmt_rx_channel(item.rx_channel);
                    }
                    else
                    {
                        while (esp_timer_get_time() < rx_end_time)
                        {
                            size_t rx_size = 0;
                            rmt_item32_t *rx_item = (rmt_item32_t *)xRingbufferReceive(rb, &rx_size, pdMS_TO_TICKS(10));
                            if (!rx_item)
                            {
                                continue;
                            }

                            int items = rx_size / sizeof(rmt_item32_t);
                            for (int j = 0; j < items; j++)
                            {
                                if (edged >= item.rx_max_edges)
                                {
                                    break;
                                }
                                if (rx_item[j].duration0 > 0 && edged < item.rx_max_edges)
                                {
                                    rx_edges[edged].level = rx_item[j].level0;
                                    rx_edges[edged].duration_us = rx_item[j].duration0;
                                    edged++;
                                }
                                if (edged >= item.rx_max_edges)
                                {
                                    break;
                                }
                                if (rx_item[j].duration1 > 0 && edged < item.rx_max_edges)
                                {
                                    rx_edges[edged].level = rx_item[j].level1;
                                    rx_edges[edged].duration_us = rx_item[j].duration1;
                                    edged++;
                                }
                            }

                            vRingbufferReturnItem(rb, (void *)rx_item);
                        }

                        rmt_rx_stop(rx_config.channel);
                        rmt_driver_uninstall(rx_config.channel);
                        release_rmt_rx_channel(item.rx_channel);
                        item.rx_channel = -1;

                        size_t payload_size = 0;
                        uint8_t *payload = build_signal_capture_payload(item.gpio, rx_edges, (uint16_t)edged, &payload_size);
                        if (payload)
                        {
                            send_event(EVENT_GPIO_SIGNAL_CAPTURED, payload, payload_size);
                            free(payload);
                        }
                        free(rx_edges);
                    }
                }

                // Send completion ACK
                event_cmd_ack_t ack = {item.cmd_id, 0, 0};
                send_event(EVENT_CMD_ACK, &ack, sizeof(event_cmd_ack_t));

                release_rmt_tx_channel(item.tx_channel);
                free(item.signal_data);
                ESP_LOGD(TAG, "TX complete, cmd_id %d", item.cmd_id);
            }
            else if (item.do_rx)
            {
                // TX empty, RX only (exchange with 0 tx edges).
                // Release unused TX channel and reserve RX channel.
                release_rmt_tx_channel(item.tx_channel);
                item.tx_channel = -1;
                if (!reserve_rmt_rx_channel(&item.rx_channel))
                {
                    event_cmd_ack_t err = {item.cmd_id, 1, IOT_ERR_RESOURCE_EXHAUSTED};
                    send_event(EVENT_ERROR, &err, sizeof(event_cmd_ack_t));
                    continue;
                }

                // Wait pre-RX delay if specified
                if (item.delay_us > 0)
                {
                    esp_rom_delay_us(item.delay_us);
                }

                // --- RX phase (same logic as TX+RX path) ---
                {
                    uint16_t filter_ticks = (item.rx_resolution_us > 0 && item.rx_resolution_us < 255)
                                                ? (uint16_t)item.rx_resolution_us
                                                : 1;
                    if (filter_ticks == 0)
                        filter_ticks = 1;
                    uint16_t idle_ticks = (item.rx_total_us > 0) ? (uint16_t)((item.rx_total_us > 60000) ? 60000 : item.rx_total_us) : 10000;

                    rmt_config_t rx_config = {
                        .rmt_mode = RMT_MODE_RX,
                        .channel = item.rx_channel,
                        .gpio_num = item.gpio,
                        .clk_div = 80,
                        .mem_block_num = 1,
                        .rx_config = {
                            .filter_en = true,
                            .filter_ticks_thresh = filter_ticks,
                            .idle_threshold = idle_ticks,
                        }};
                    esp_err_t rx_ret = rmt_config(&rx_config);
                    if (rx_ret != ESP_OK)
                    {
                        event_cmd_ack_t err = {item.cmd_id, 1, (rx_ret == ESP_ERR_NOT_FOUND) ? IOT_ERR_RESOURCE_EXHAUSTED : IOT_ERR_DRIVER};
                        send_event(EVENT_ERROR, &err, sizeof(event_cmd_ack_t));
                        release_rmt_rx_channel(item.rx_channel);
                        continue;
                    }
                    rx_ret = rmt_driver_install(rx_config.channel, 1000, 0);
                    if (rx_ret != ESP_OK)
                    {
                        event_cmd_ack_t err = {item.cmd_id, 1, (rx_ret == ESP_ERR_NOT_SUPPORTED) ? IOT_ERR_UNSUPPORTED : IOT_ERR_RESOURCE_EXHAUSTED};
                        send_event(EVENT_ERROR, &err, sizeof(event_cmd_ack_t));
                        release_rmt_rx_channel(item.rx_channel);
                        continue;
                    }
                    rmt_rx_start(rx_config.channel, true);

                    RingbufHandle_t rb = NULL;
                    rmt_get_ringbuf_handle(rx_config.channel, &rb);

                    uint32_t rx_end_time = esp_timer_get_time() + item.rx_total_us;
                    int edged = 0;
                    signal_edge_t *rx_edges = malloc(sizeof(signal_edge_t) * item.rx_max_edges);
                    if (!rx_edges)
                    {
                        event_cmd_ack_t err = {item.cmd_id, 1, 5};
                        send_event(EVENT_ERROR, &err, sizeof(event_cmd_ack_t));
                        rmt_rx_stop(rx_config.channel);
                        rmt_driver_uninstall(rx_config.channel);
                        release_rmt_rx_channel(item.rx_channel);
                    }
                    else
                    {
                        while (esp_timer_get_time() < rx_end_time)
                        {
                            size_t rx_size = 0;
                            rmt_item32_t *rx_item = (rmt_item32_t *)xRingbufferReceive(rb, &rx_size, pdMS_TO_TICKS(10));
                            if (!rx_item)
                                continue;

                            int items = rx_size / sizeof(rmt_item32_t);
                            for (int j = 0; j < items; j++)
                            {
                                if (edged >= item.rx_max_edges)
                                    break;
                                if (rx_item[j].duration0 > 0 && edged < item.rx_max_edges)
                                {
                                    rx_edges[edged].level = rx_item[j].level0;
                                    rx_edges[edged].duration_us = rx_item[j].duration0;
                                    edged++;
                                }
                                if (edged >= item.rx_max_edges)
                                    break;
                                if (rx_item[j].duration1 > 0 && edged < item.rx_max_edges)
                                {
                                    rx_edges[edged].level = rx_item[j].level1;
                                    rx_edges[edged].duration_us = rx_item[j].duration1;
                                    edged++;
                                }
                            }
                            vRingbufferReturnItem(rb, (void *)rx_item);
                        }
                        rmt_rx_stop(rx_config.channel);
                        rmt_driver_uninstall(rx_config.channel);

                        size_t payload_size = 0;
                        uint8_t *payload = build_signal_capture_payload(item.gpio, rx_edges, (uint16_t)edged, &payload_size);
                        if (payload)
                        {
                            send_event(EVENT_GPIO_SIGNAL_CAPTURED, payload, payload_size);
                            free(payload);
                        }
                        free(rx_edges);
                    }
                    release_rmt_rx_channel(item.rx_channel);
                    item.rx_channel = -1;
                }

                // Send completion ACK
                event_cmd_ack_t ack = {item.cmd_id, 0, 0};
                send_event(EVENT_CMD_ACK, &ack, sizeof(event_cmd_ack_t));
            }
            else
            {
                // No signal data and no RX — nothing to do
                event_cmd_ack_t ack = {item.cmd_id, 0, 0};
                send_event(EVENT_CMD_ACK, &ack, sizeof(event_cmd_ack_t));
                release_rmt_tx_channel(item.tx_channel);
                free(item.signal_data);
            }
        }
    }
}

// Signal RX ISR - record level transitions with timestamps
static volatile int capture_gpio = -1;
static volatile int capture_edge_count = 0;
static volatile int64_t capture_last_time = 0;
static signal_edge_t *capture_edges = NULL;
static int capture_max_edges = 0;
static bool isr_service_installed = false;

static void signal_capture_isr(void *arg)
{
    int gpio_num = (int)(uintptr_t)arg;
    int64_t now = esp_timer_get_time();

    if (capture_edges && capture_edge_count < capture_max_edges)
    {
        int level = gpio_get_level(gpio_num);
        uint32_t duration_us = (uint32_t)(now - capture_last_time);

        capture_edges[capture_edge_count].level = level;
        capture_edges[capture_edge_count].duration_us = duration_us;
        capture_edge_count++;
        capture_last_time = now;
    }
}

// GPIO Signal RX Task - handles signal capture and recording
void gpio_signal_rx_task(void *pvParameters)
{
    gpio_signal_rx_item_t item;

    ESP_LOGI(TAG, "GPIO Signal RX task started");

    while (1)
    {
        if (xQueueReceive(get_signal_rx_queue(), &item, portMAX_DELAY) == pdTRUE)
        {
            ESP_LOGI(TAG, "RX: GPIO %d, timeout_us %d, max_edges %d",
                     item.gpio, item.timeout_us, item.max_edges);

            // Allocate edge buffer
            signal_edge_t *edges = (signal_edge_t *)malloc(sizeof(signal_edge_t) * item.max_edges);
            if (!edges)
            {
                event_cmd_ack_t err = {item.cmd_id, 1, 5};
                send_event(EVENT_ERROR, &err, sizeof(event_cmd_ack_t));
                release_rmt_rx_channel(item.rx_channel);
                continue;
            }

            // Setup ISR for capture
            capture_gpio = item.gpio;
            capture_edges = edges;
            capture_max_edges = item.max_edges;
            capture_edge_count = 0;
            capture_last_time = esp_timer_get_time();

            if (!isr_service_installed)
            {
                esp_err_t isr_ret = gpio_install_isr_service(0);
                if (isr_ret == ESP_OK || isr_ret == ESP_ERR_INVALID_STATE)
                {
                    isr_service_installed = true;
                }
                else
                {
                    event_cmd_ack_t err = {item.cmd_id, 1, 6};
                    send_event(EVENT_ERROR, &err, sizeof(event_cmd_ack_t));
                    free(edges);
                    capture_edges = NULL;
                    release_rmt_rx_channel(item.rx_channel);
                    continue;
                }
            }

            // Ensure edge interrupt is enabled for signal capture.
            gpio_set_intr_type(item.gpio, GPIO_INTR_ANYEDGE);
            gpio_intr_enable(item.gpio);
            gpio_isr_handler_add(item.gpio, signal_capture_isr, (void *)(uintptr_t)item.gpio);

            // Wait for signal capture with timeout
            int64_t start_time = esp_timer_get_time();
            while ((esp_timer_get_time() - start_time) < item.timeout_us)
            {
                vTaskDelay(1);
                if (capture_edge_count >= item.max_edges)
                {
                    break;
                }
            }

            // Build and send captured data event
            size_t payload_size = 0;
            uint8_t *payload = build_signal_capture_payload(item.gpio, edges, (uint16_t)capture_edge_count, &payload_size);

            if (payload)
            {
                send_event(EVENT_GPIO_SIGNAL_CAPTURED, payload, payload_size);
                free(payload);
            }

            // Cleanup
            gpio_isr_handler_remove(item.gpio);
            gpio_intr_disable(item.gpio);
            free(edges);
            capture_edges = NULL;
            release_rmt_rx_channel(item.rx_channel);

            // Send ACK
            event_cmd_ack_t ack = {item.cmd_id, 0, 0};
            send_event(EVENT_CMD_ACK, &ack, sizeof(event_cmd_ack_t));

            ESP_LOGD(TAG, "RX complete, edges captured: %d", capture_edge_count);
        }
    }
}
