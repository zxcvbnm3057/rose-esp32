#include "iot_agent.h"
#include "config.h"
#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "nvs_flash.h"
#include "lwip/sockets.h"
#include "driver/gpio.h"
#include "driver/uart.h"
#include "driver/adc.h"
#include "esp_timer.h"

// Global variables
static const char *TAG = "iot_agent";

// Configuration
const char *SERVER_IP = SERVER_IP_STR;
uint16_t SERVER_PORT = SERVER_PORT_NUM;
const char *WIFI_SSID = WIFI_SSID_STR;
const char *WIFI_PASS = WIFI_PASS_STR;

// Status
gpio_status_t gpio_table[31] = {0};
uart_status_t uart_table[IOT_UART_NUM_MAX] = {0};
thread_device_t thread_table[16] = {0};
QueueHandle_t cmd_queue;
QueueHandle_t send_queue;
SemaphoreHandle_t resource_mutex;
int client_sock = -1;
uint16_t cmd_counter = 0;
int connection_state = 0;
uint32_t last_heartbeat_time = 0;
uint32_t reconnect_interval = 1000; // Start with 1s

// WiFi event handler (STA mode)
static void wifi_event_handler(void *arg, esp_event_base_t event_base,
                               int32_t event_id, void *event_data)
{
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START)
    {
        esp_wifi_connect();
        ESP_LOGI(TAG, "WiFi connecting...");
    }
    else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED)
    {
        ESP_LOGW(TAG, "WiFi disconnected, reconnecting...");
        esp_wifi_connect();
    }
    else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP)
    {
        ip_event_got_ip_t *event = (ip_event_got_ip_t *)event_data;
        ESP_LOGI(TAG, "WiFi connected, IP: " IPSTR, IP2STR(&event->ip_info.ip));
    }
}

// Initialize WiFi in STA mode
void wifi_init_sta(void)
{
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    esp_event_handler_instance_t instance_any_id;
    esp_event_handler_instance_t instance_got_ip;
    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT,
                                                        ESP_EVENT_ANY_ID,
                                                        &wifi_event_handler,
                                                        NULL,
                                                        &instance_any_id));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT,
                                                        IP_EVENT_STA_GOT_IP,
                                                        &wifi_event_handler,
                                                        NULL,
                                                        &instance_got_ip));

    wifi_config_t wifi_config = {
        .sta = {
            .ssid = {0},
            .password = {0},
        },
    };
    strncpy((char *)wifi_config.sta.ssid, WIFI_SSID, sizeof(wifi_config.sta.ssid) - 1);
    strncpy((char *)wifi_config.sta.password, WIFI_PASS, sizeof(wifi_config.sta.password) - 1);

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_LOGI(TAG, "WiFi init STA mode");
}

// Initialize resource tables
void init_resource_tables(void)
{
    for (int i = 0; i < 31; i++)
    {
        gpio_table[i].mode = 0xFF; // Uninitialized
        gpio_table[i].pull = 0;
        gpio_table[i].edge = 0;
        gpio_table[i].owner = 0;
        gpio_table[i].in_use = 0;
        gpio_table[i].value = 0;
        gpio_table[i].adc_value = 0;
        gpio_table[i].adc_voltage_mv = 0;
        gpio_table[i].last_ts = 0;
    }
    for (int i = 0; i < IOT_UART_NUM_MAX; i++)
    {
        uart_table[i].tx_pin = 0xFF;
        uart_table[i].rx_pin = 0xFF;
        uart_table[i].baudrate = 0;
        uart_table[i].owner = 0;
        uart_table[i].in_use = 0;
        uart_table[i].event_queue = NULL;
    }
    for (int i = 0; i < 16; i++)
    {
        thread_table[i].device_id = 0xFFFF;
        thread_table[i].online = 0;
    }
}

// Main app
void app_main(void)
{
    ESP_LOGI(TAG, "Starting IoT Agent");

    // Initialize resources
    resource_mutex = xSemaphoreCreateMutex();
    cmd_queue = xQueueCreate(QUEUE_SIZE, sizeof(msg_frame_t *));
    send_queue = xQueueCreate(QUEUE_SIZE, sizeof(msg_frame_t *));

    if (!resource_mutex || !cmd_queue || !send_queue)
    {
        ESP_LOGE(TAG, "Failed to create queues/mutex");
        return;
    }

    init_resource_tables();

    // Initialize GPIO signal queues
    gpio_signal_init();

    // Initialize NVS before BLE/WiFi
    nvs_flash_init();
    init_sync_state();

    // Initialize BLE
    ble_manager_init();

    // Initialize WiFi
    wifi_init_sta();
    vTaskDelay(pdMS_TO_TICKS(3000)); // Wait for WiFi to connect

    // Create tasks
    xTaskCreate(tcp_client_task, "tcp_client", 4096, NULL, 5, NULL);
    xTaskCreate(command_dispatcher_task, "cmd_dispatch", 4096, NULL, 5, NULL);
    xTaskCreate(send_task, "send_task", 4096, NULL, 4, NULL);
    xTaskCreate(heartbeat_task, "heartbeat", 2048, NULL, 3, NULL);
    xTaskCreate(uart_rx_task, "uart_rx", 2048, NULL, 3, NULL);
    xTaskCreate(gpio_signal_tx_task, "gpio_tx", 3072, NULL, 6, NULL);
    xTaskCreate(gpio_signal_rx_task, "gpio_rx", 3072, NULL, 6, NULL);
    xTaskCreate(ble_rssi_task, "ble_rssi", 2048, NULL, 3, NULL);

    ESP_LOGI(TAG, "All tasks created");

    // Keep main task alive
    while (1)
    {
        vTaskDelay(pdMS_TO_TICKS(10000));
    }
}
