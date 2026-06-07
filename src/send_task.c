#include "iot_agent.h"
#include <string.h>
#include <errno.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "lwip/sockets.h"
#include <stdlib.h>

static const char *TAG = "send_task";

// Send Task - processes event queue and sends to TCP server
void send_task(void *pvParameters)
{
    msg_frame_t *frame;
    uint8_t disconnected_warned = 0;

    ESP_LOGI(TAG, "Send task started");

    while (1)
    {
        if (xQueueReceive(send_queue, &frame, portMAX_DELAY) == pdTRUE)
        {
            if (client_sock >= 0 && connection_state)
            {
                size_t send_size = sizeof(msg_frame_t) + frame->length;
                uint8_t event_opcode = (frame->length > 0) ? frame->payload[0] : 0xFF;
                int sent = send(client_sock, (uint8_t *)frame, send_size, 0);
                if (sent < 0)
                {
                    ESP_LOGW(TAG, "send failed: errno %d, closing socket", errno);
                    if (client_sock >= 0)
                    {
                        close(client_sock);
                        client_sock = -1;
                    }
                    connection_state = 0;
                    last_heartbeat_time = 0;
                }
                else
                {
                    disconnected_warned = 0;
                    last_heartbeat_time = esp_timer_get_time() / 1000;
                    ESP_LOGD(TAG, "Sent event msg_type=0x%02X opcode=0x%02X, cmd_id %d, len %d",
                             frame->type, event_opcode, frame->cmd_id, frame->length);
                }
            }
            else
            {
                if (!disconnected_warned)
                {
                    uint8_t event_opcode = (frame->length > 0) ? frame->payload[0] : 0xFF;
                    ESP_LOGW(TAG, "No client connected, dropping events (msg_type=0x%02X opcode=0x%02X)",
                             frame->type, event_opcode);
                    disconnected_warned = 1;
                }
            }
            free(frame);
        }
    }
}

// Send Event - constructs event frame and queues it
void send_event(uint8_t opcode, void *payload, size_t payload_size)
{
    // Add 1 byte for opcode
    size_t payload_len = 1 + payload_size;
    size_t total_size = sizeof(msg_frame_t) + payload_len;

    // Allocate frame
    msg_frame_t *frame = (msg_frame_t *)malloc(total_size);
    if (!frame)
    {
        ESP_LOGE(TAG, "Failed to malloc frame");
        return;
    }

    // Build frame
    frame->version = 1;
    frame->type = MSG_TYPE_EVENT;
    frame->length = (uint16_t)payload_len;
    frame->cmd_id = cmd_counter++;
    frame->payload[0] = opcode;

    // Copy payload
    if (payload && payload_size > 0)
    {
        memcpy(&frame->payload[1], payload, payload_size);
    }

    // Calculate CRC
    frame->crc = calculate_crc((uint8_t *)frame, sizeof(msg_frame_t) + payload_len - 2); // Exclude CRC field

    // Queue it — tail-drop: if full, discard the oldest item to make room
    // so that stale events don't block fresh ones (critical after reconnect).
    if (xQueueSend(send_queue, &frame, 0) != pdTRUE)
    {
        msg_frame_t *stale = NULL;
        if (xQueueReceive(send_queue, &stale, 0) == pdTRUE)
        {
            free(stale);
        }
        if (xQueueSend(send_queue, &frame, 0) != pdTRUE)
        {
            ESP_LOGW(TAG, "Send queue still full after tail-drop, dropping event");
            free(frame);
        }
    }
}

// CRC calculation using XOR (simple polynomial)
uint16_t calculate_crc(uint8_t *data, size_t len)
{
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < len; i++)
    {
        crc ^= data[i];
        for (int j = 0; j < 8; j++)
        {
            if (crc & 1)
            {
                crc = (crc >> 1) ^ 0xA001;
            }
            else
            {
                crc >>= 1;
            }
        }
    }
    return crc;
}
