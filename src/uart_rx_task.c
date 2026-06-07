#include "iot_agent.h"
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "driver/uart.h"
#include "esp_timer.h"
#include <stdlib.h>

static const char *TAG = "uart_rx";

static inline TickType_t wait_ticks_ms(uint32_t ms)
{
    TickType_t ticks = pdMS_TO_TICKS(ms);
    return (ticks > 0) ? ticks : 1;
}

// UART RX Task - consume UART driver events and forward RX payloads.
void uart_rx_task(void *pvParameters)
{
    uint8_t rx_buf[256];
    uart_event_t uart_event;

    ESP_LOGI(TAG, "UART RX task started");

    while (1)
    {
        int active_uarts = 0;
        for (int uart_id = 0; uart_id < IOT_UART_NUM_MAX; uart_id++)
        {
            QueueHandle_t q = uart_table[uart_id].event_queue;
            if (!uart_table[uart_id].in_use || q == NULL)
            {
                continue;
            }

            active_uarts++;

            int processed_events = 0;
            while (processed_events < 8 && xQueueReceive(q, &uart_event, wait_ticks_ms(20)) == pdTRUE)
            {
                processed_events++;
                if (uart_event.type == UART_DATA)
                {
                    int remaining = (int)uart_event.size;
                    int processed_chunks = 0;
                    // Bound one pass work to avoid starving lower-priority tasks/idle task.
                    while (remaining > 0 && processed_chunks < 8)
                    {
                        int chunk = remaining > (int)sizeof(rx_buf) ? (int)sizeof(rx_buf) : remaining;
                        int available = uart_read_bytes(uart_id, rx_buf, chunk, wait_ticks_ms(20));
                        if (available <= 0)
                        {
                            break;
                        }

                        size_t event_size = sizeof(event_uart_rx_t) + (size_t)available;
                        uint8_t *event_buf = (uint8_t *)malloc(event_size);
                        if (!event_buf)
                        {
                            break;
                        }

                        event_uart_rx_t *event = (event_uart_rx_t *)event_buf;
                        event->uart_id = uart_id;
                        event->length = (uint16_t)available;
                        event->timestamp_us = esp_timer_get_time();
                        memcpy(&event_buf[sizeof(event_uart_rx_t)], rx_buf, (size_t)available);

                        send_event(EVENT_UART_RX, event_buf, event_size);
                        free(event_buf);

                        remaining -= available;
                        processed_chunks++;
                        ESP_LOGD(TAG, "UART %d RX chunk: %d bytes", uart_id, available);

                        if ((processed_chunks % 2) == 0)
                        {
                            vTaskDelay(wait_ticks_ms(10));
                        }
                    }

                    if (remaining > 0)
                    {
                        ESP_LOGD(TAG, "UART %d RX deferred, remaining=%d", uart_id, remaining);
                    }
                }
                else if (uart_event.type == UART_FIFO_OVF || uart_event.type == UART_BUFFER_FULL)
                {
                    uart_flush_input(uart_id);
                    xQueueReset(q);
                    ESP_LOGW(TAG, "UART %d overflow, input flushed", uart_id);
                }
                else if (uart_event.type == UART_BREAK || uart_event.type == UART_FRAME_ERR || uart_event.type == UART_PARITY_ERR)
                {
                    ESP_LOGW(TAG, "UART %d line error type=%d", uart_id, uart_event.type);
                }

                // Keep scheduler responsive when event queue is busy.
                vTaskDelay(wait_ticks_ms(10));
            }
        }

        if (active_uarts == 0)
        {
            // No configured UART yet: sleep longer to avoid needless wakeups.
            vTaskDelay(wait_ticks_ms(100));
        }
        else
        {
            vTaskDelay(wait_ticks_ms(20));
        }
    }
}
