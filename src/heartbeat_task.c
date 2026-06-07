#include "iot_agent.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "lwip/sockets.h"

static const char *TAG = "heartbeat";

// Heartbeat task - sends periodic heartbeat and monitors connection
void heartbeat_task(void *pvParameters)
{
    uint32_t heartbeat_interval = 10000; // 10 seconds
    uint32_t last_send_time = 0;

    ESP_LOGI(TAG, "Heartbeat task started");

    while (1)
    {
        uint32_t current_time = esp_timer_get_time() / 1000; // Convert to ms

        // Send heartbeat every 10 seconds if connected
        if (connection_state == 1 && (current_time - last_send_time) >= heartbeat_interval)
        {
            event_heartbeat_t hb = {
                .timestamp = current_time,
                .connection_state = 1};
            send_event(EVENT_HEARTBEAT, &hb, sizeof(event_heartbeat_t));
            last_send_time = current_time;
            last_heartbeat_time = current_time;
            ESP_LOGD(TAG, "Heartbeat sent");
        }

        // Check for heartbeat timeout (30s)
        if (connection_state == 1 && last_heartbeat_time > 0)
        {
            if ((current_time - last_heartbeat_time) > 30000)
            {
                ESP_LOGW(TAG, "Heartbeat timeout, forcing reconnect");
                connection_state = 0;
                if (client_sock >= 0)
                {
                    close(client_sock);
                    client_sock = -1;
                }
            }
        }

        vTaskDelay(pdMS_TO_TICKS(1000)); // Check every second
    }
}
