#ifndef IOT_AGENT_H
#define IOT_AGENT_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"

// Constants
#define TCP_PORT 8080
#define QUEUE_SIZE 64
#define CMD_BUF_SIZE 256
#define MAX_PAYLOAD_SIZE 8192 // Maximum allowed command payload (handles 1600+ edge signals)

// Message types
#define MSG_TYPE_CMD 0x01
#define MSG_TYPE_ACK 0x02
#define MSG_TYPE_EVENT 0x03
#define MSG_TYPE_ERROR 0x04

// Command opcodes
#define CMD_GPIO_CONFIG 0x10
#define CMD_GPIO_SET 0x11
#define CMD_GPIO_GET 0x12
#define CMD_ADC_SAMPLE 0x13
#define CMD_GPIO_SIGNAL_TX 0x14
#define CMD_GPIO_SIGNAL_RX 0x15
#define CMD_GPIO_SIGNAL_EXCHANGE 0x16
#define CMD_UART_CONFIG 0x20
#define CMD_UART_SEND 0x21
#define CMD_UART_READ 0x22
#define CMD_PORT_BIND 0x30
#define CMD_PORT_UNBIND 0x31
#define CMD_PORT_STATUS 0x32
#define CMD_THREAD_PASSTHROUGH 0x40
#define CMD_BLE_ENABLE_PAIRING 0x50
#define CMD_BLE_DISABLE_PAIRING 0x51
#define CMD_BLE_GET_PEERS 0x52
#define CMD_SYNC_REQUEST 0x01
#define CMD_SYN 0x02
#define CMD_BLE_START_SCAN 0x53
#define CMD_HEARTBEAT 0xFE
#define CMD_PING 0xFF

// Event opcodes
#define EVENT_SYNC_RESPONSE 0x66
#define EVENT_CMD_ACK 0x20
#define EVENT_GPIO_VALUE 0x21
#define EVENT_GPIO_EDGE 0x22
#define EVENT_ADC_VALUE 0x23
#define EVENT_GPIO_SIGNAL_CAPTURED 0x24
#define EVENT_UART_RX 0x30
#define EVENT_THREAD_RESPONSE 0x40
#define EVENT_PORT_STATUS 0x50
#define EVENT_BLE_PAIRING_ENABLED 0x60
#define EVENT_BLE_PAIRING_DISABLED 0x61
#define EVENT_BLE_PEER_CONNECTED 0x62
#define EVENT_BLE_PEER_DISCONNECTED 0x63
#define EVENT_BLE_PEERS_LIST 0x64
#define EVENT_BLE_RSSI 0x65
#define EVENT_ERROR 0xFE
#define EVENT_HEARTBEAT 0xFD

// Error codes propagated to host via EVENT_ERROR
#define IOT_ERR_INVALID_ARG 1
#define IOT_ERR_INVALID_STATE 2
#define IOT_ERR_DRIVER 3
#define IOT_ERR_RESOURCE_CONFLICT 4
#define IOT_ERR_UNSUPPORTED 5
#define IOT_ERR_NOT_FOUND 6
#define IOT_ERR_RESOURCE_EXHAUSTED 7

// GPIO modes
#define IOT_GPIO_MODE_INPUT 0
#define IOT_GPIO_MODE_OUTPUT 1
#define IOT_GPIO_MODE_INTERRUPT 2
#define IOT_GPIO_MODE_ADC 3
#define IOT_GPIO_MODE_SIGNAL 4

// UART configs
#define IOT_UART_NUM_MAX 2

// Structures
#pragma pack(push, 1)
typedef struct
{
    uint8_t version;
    uint8_t type;
    uint16_t length;
    uint16_t cmd_id;
    uint16_t crc;
    uint8_t payload[0];
} msg_frame_t;

typedef struct
{
    uint8_t gpio;
    uint8_t mode;
    uint8_t pull;
    uint8_t edge;
} cmd_gpio_config_t;

typedef struct
{
    uint8_t gpio;
    uint8_t value;
} cmd_gpio_set_t;

typedef struct
{
    uint8_t gpio;
} cmd_gpio_get_t;

typedef struct
{
    uint8_t gpio;
    uint8_t samples;
} cmd_adc_sample_t;

typedef struct
{
    uint8_t gpio;
    uint16_t signal_len;
    uint32_t delay_us;
} cmd_gpio_signal_tx_t;

typedef struct
{
    uint8_t gpio;
    uint32_t timeout_us;
    uint16_t max_edges;
} cmd_gpio_signal_rx_t;

typedef struct
{
    uint8_t gpio;
    uint16_t tx_len;
    uint32_t delay_us;
    uint32_t rx_total_us;
    uint16_t rx_max_edges;
    uint32_t rx_resolution_us;
    // tx sequence follows: tx_len * (1B level + 4B duration_us)
} cmd_gpio_signal_exchange_t;

typedef struct
{
    uint8_t uart_id;
    uint32_t baudrate;
    uint8_t data_bits;
    uint8_t parity;
    uint8_t stop_bits;
    uint8_t tx_gpio;
    uint8_t rx_gpio;
} cmd_uart_config_t;

typedef struct
{
    uint8_t uart_id;
    uint16_t length;
    uint8_t data[0];
} cmd_uart_send_t;

typedef struct
{
    uint8_t uart_id;
    uint16_t length;
} cmd_uart_read_t;

typedef struct
{
    uint8_t resource_type; // 0=gpio, 1=uart
    uint8_t id;
    uint16_t owner_id;
} cmd_port_bind_t;

typedef struct
{
    uint8_t resource_type;
    uint8_t id;
} cmd_port_status_t;

typedef struct
{
    uint16_t device_id;
    uint16_t payload_len;
    uint32_t correlation_id;
    uint8_t payload[0];
} cmd_thread_passthrough_t;

typedef struct
{
    uint32_t correlation_id;
    uint8_t stage; // 0=command ack sync, 1=result sync
} cmd_syn_t;

typedef struct
{
    uint32_t timestamp;
} cmd_heartbeat_t;

typedef struct
{
    uint32_t timeout_s;
} cmd_ble_enable_pairing_t;

typedef struct
{
    uint8_t reason;
} cmd_ble_disable_pairing_t;

typedef struct
{
    uint8_t dummy;
} cmd_ble_get_peers_t;

typedef struct
{
    uint32_t interval_s;
} cmd_ble_start_scan_t;

typedef struct
{
    uint16_t cmd_id;
    uint8_t status;
    uint8_t error_code;
    uint32_t correlation_id;
} event_cmd_ack_t;

typedef struct
{
    uint8_t gpio;
    uint8_t value;
    int64_t timestamp_us;
} event_gpio_value_t;

typedef struct
{
    uint8_t gpio;
    uint8_t edge_type;
    int64_t timestamp_us;
} event_gpio_edge_t;

typedef struct
{
    uint8_t gpio;
    uint16_t value;
    int64_t timestamp_us;
} event_adc_value_t;

typedef struct
{
    uint8_t gpio;
    uint16_t edge_count;
    int64_t timestamp_us;
} event_gpio_signal_captured_t;

typedef struct
{
    uint8_t uart_id;
    uint16_t length;
    int64_t timestamp_us;
    uint8_t data[0];
} event_uart_rx_t;

typedef struct
{
    uint16_t device_id;
    uint8_t online;
    uint8_t metadata[64];
} event_thread_state_t;

typedef struct
{
    uint8_t resource_type;
    uint8_t id;
    uint8_t mode;
    uint16_t owner;
    uint8_t in_use;
    uint8_t value;
} event_port_status_t;

typedef struct
{
    uint16_t device_id;
    uint16_t payload_len;
    uint32_t correlation_id;
    int64_t timestamp_us;
    uint8_t payload[0];
} event_thread_response_t;

typedef struct
{
    uint32_t session_version;
    uint16_t pending_cmd_count;
    uint16_t pending_thread_count;
    uint16_t port_status_count;
} event_sync_response_t;

typedef struct
{
    uint16_t cmd_id;
    uint8_t err_code;
    char message[64];
} event_error_t;

typedef struct
{
    uint32_t timestamp;
    uint8_t connection_state;
} event_heartbeat_t;

typedef struct
{
    uint8_t pin_code[6];
    uint32_t timeout_s;
} event_ble_pairing_enabled_t;

typedef struct
{
    uint8_t reason;
} event_ble_pairing_disabled_t;

typedef struct
{
    uint8_t peer_mac[6];
    int8_t rssi;
} event_ble_peer_connected_t;

typedef struct
{
    uint8_t peer_mac[6];
    uint8_t reason;
} event_ble_peer_disconnected_t;

typedef struct
{
    uint8_t peer_count;
} event_ble_peers_list_t;

typedef struct
{
    uint8_t peer_mac[6];
    int8_t rssi;
    int64_t timestamp_us;
} event_ble_rssi_t;

#pragma pack(pop)

// Resource tables
typedef struct
{
    uint8_t mode;
    uint16_t owner;
    uint8_t in_use;
    uint8_t value;
    int64_t last_ts;
} gpio_status_t;

typedef struct
{
    uint8_t tx_pin;
    uint8_t rx_pin;
    uint32_t baudrate;
    uint16_t owner;
    uint8_t in_use;
    QueueHandle_t event_queue;
} uart_status_t;

typedef struct
{
    uint16_t device_id;
    uint8_t online;
    uint8_t metadata[64];
} thread_device_t;

typedef struct
{
    uint8_t peer_mac[6];
    int8_t rssi;
    uint32_t conn_time_s;
    uint8_t in_use;
} ble_peer_t;

// Global variables externs
extern gpio_status_t gpio_table[31];
extern uart_status_t uart_table[IOT_UART_NUM_MAX];
extern thread_device_t thread_table[16]; // Max 16 devices
extern ble_peer_t ble_peer_table[4];     // Max 4 BLE peers
extern QueueHandle_t cmd_queue;
extern QueueHandle_t send_queue;
extern SemaphoreHandle_t resource_mutex;
extern int client_sock;
extern uint16_t cmd_counter;
extern const char *SERVER_IP;
extern uint16_t SERVER_PORT;
extern int connection_state; // 0=disconnected, 1=connected
extern uint32_t last_heartbeat_time;
extern uint32_t reconnect_interval;
extern uint8_t ble_pairing_enabled;
extern uint32_t ble_pairing_timeout_s;
extern uint8_t ble_rssi_scan_enabled;
extern uint32_t ble_rssi_interval_s;

// Function prototypes
void wifi_init_sta(void);
void tcp_client_task(void *pvParameters);
void heartbeat_task(void *pvParameters);
void command_dispatcher_task(void *pvParameters);
void send_task(void *pvParameters);
void handle_command(msg_frame_t *frame);
void send_event(uint8_t opcode, void *payload, size_t payload_size);
uint16_t calculate_crc(uint8_t *data, size_t len);
void gpio_isr_handler(void *arg);
void uart_rx_task(void *pvParameters);
void gpio_signal_tx_task(void *pvParameters);
void gpio_signal_rx_task(void *pvParameters);
void gpio_signal_init(void);
QueueHandle_t get_signal_tx_queue(void);
QueueHandle_t get_signal_rx_queue(void);
void init_resource_tables(void);
void init_sync_state(void);

// ADC functions
uint16_t adc_read_sample(uint8_t gpio, uint8_t samples);

// Signal capture functions
typedef struct
{
    uint8_t level;
    uint32_t duration_us;
} signal_edge_t;

// Signal operation queue items
typedef struct
{
    uint16_t cmd_id;
    uint8_t gpio;
    uint16_t signal_len;
    uint32_t delay_us;
    uint8_t *signal_data;
    int8_t tx_channel;
    int8_t rx_channel;
    // RX parameters
    uint8_t do_rx;
    uint32_t rx_total_us;
    uint16_t rx_max_edges;
    uint32_t rx_resolution_us;
} gpio_signal_tx_item_t;

typedef struct
{
    uint16_t cmd_id;
    uint8_t gpio;
    uint32_t timeout_us;
    uint16_t max_edges;
    int8_t rx_channel;
} gpio_signal_rx_item_t;

void gpio_signal_capture_handler(void *arg);
int gpio_signal_capture(uint8_t gpio, signal_edge_t *edges, int max_edges, uint32_t timeout_us);
bool reserve_rmt_tx_channel(int8_t *channel_out);
bool reserve_rmt_rx_channel(int8_t *channel_out);
void release_rmt_tx_channel(int8_t channel);
void release_rmt_rx_channel(int8_t channel);

// BLE functions
void ble_manager_init(void);
void ble_rssi_task(void *pvParameters);
void ble_enable_pairing(uint32_t timeout_s);
void ble_disable_pairing(void);
void ble_get_peers_list(ble_peer_t *peers, int *peer_count);
void ble_start_rssi_scan(uint32_t interval_s);
void ble_stop_rssi_scan(void);

#endif // IOT_AGENT_H