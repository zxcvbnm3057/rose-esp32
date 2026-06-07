#include "iot_agent.h"
#include <string.h>
#include <errno.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "lwip/sockets.h"
#include "lwip/netdb.h"
#include "lwip/ip_addr.h"
#include <fcntl.h>
#include "esp_timer.h"

static const char *TAG = "tcp_client";
static const uint32_t CONNECT_TIMEOUT_MS = 3000;

static int connect_with_timeout(int sock, const struct sockaddr *addr, socklen_t addrlen, uint32_t timeout_ms)
{
    int flags = fcntl(sock, F_GETFL, 0);
    if (flags < 0)
    {
        return -1;
    }

    if (fcntl(sock, F_SETFL, flags | O_NONBLOCK) < 0)
    {
        return -1;
    }

    int ret = connect(sock, addr, addrlen);
    if (ret == 0)
    {
        fcntl(sock, F_SETFL, flags);
        return 0;
    }

    if (errno != EINPROGRESS)
    {
        fcntl(sock, F_SETFL, flags);
        return -1;
    }

    fd_set write_fds;
    FD_ZERO(&write_fds);
    FD_SET(sock, &write_fds);

    struct timeval tv = {
        .tv_sec = timeout_ms / 1000,
        .tv_usec = (timeout_ms % 1000) * 1000,
    };

    ret = select(sock + 1, NULL, &write_fds, NULL, &tv);
    if (ret <= 0)
    {
        if (ret == 0)
        {
            errno = ETIMEDOUT;
        }
        fcntl(sock, F_SETFL, flags);
        return -1;
    }

    int so_error = 0;
    socklen_t so_len = sizeof(so_error);
    if (getsockopt(sock, SOL_SOCKET, SO_ERROR, &so_error, &so_len) < 0)
    {
        fcntl(sock, F_SETFL, flags);
        return -1;
    }

    fcntl(sock, F_SETFL, flags);
    if (so_error != 0)
    {
        errno = so_error;
        return -1;
    }

    return 0;
}

// TCP client reconnection task
void tcp_client_task(void *pvParameters)
{
    struct sockaddr_in server_addr = {0};
    uint32_t retry_count = 0;
    // Static buffer — avoids heap fragmentation from a persistent 8 KB allocation
    // that would otherwise sit in the heap for the entire device lifetime.
    static uint8_t rx_buf[MAX_PAYLOAD_SIZE + sizeof(msg_frame_t)];
    const size_t rx_buf_size = sizeof(rx_buf);
    size_t buffered_len = 0;

    ESP_LOGI(TAG, "TCP Client task started, connecting to %s:%d", SERVER_IP, SERVER_PORT);

    while (1)
    {
        // Close previous socket if exists
        if (client_sock >= 0)
        {
            close(client_sock);
            client_sock = -1;
        }

        // Create socket
        client_sock = socket(AF_INET, SOCK_STREAM, IPPROTO_IP);
        if (client_sock < 0)
        {
            ESP_LOGE(TAG, "Unable to create socket: errno %d", errno);
            vTaskDelay(pdMS_TO_TICKS(reconnect_interval));
            retry_count++;
            if (reconnect_interval < 30000)
            { // Max 30s
                reconnect_interval *= 2;
            }
            continue;
        }

        // Setup server address
        server_addr.sin_addr.s_addr = inet_addr(SERVER_IP);
        server_addr.sin_family = AF_INET;
        server_addr.sin_port = htons(SERVER_PORT);

        // Connect to server
        int ret = connect_with_timeout(client_sock, (struct sockaddr *)&server_addr, sizeof(server_addr), CONNECT_TIMEOUT_MS);
        if (ret != 0)
        {
            ESP_LOGE(TAG, "Socket connect failed: errno %d, retry in %dms", errno, reconnect_interval);
            close(client_sock);
            client_sock = -1;
            vTaskDelay(pdMS_TO_TICKS(reconnect_interval));
            retry_count++;
            reconnect_interval = (reconnect_interval * 2 > 30000) ? 30000 : reconnect_interval * 2;
            continue;
        }

        ESP_LOGI(TAG, "Successfully connected to TCP server");
        connection_state = 1;
        last_heartbeat_time = esp_timer_get_time() / 1000;
        reconnect_interval = 1000; // Reset to 1s
        retry_count = 0;

        // Set socket timeout to 30s for idle detection
        struct timeval tv = {
            .tv_sec = 30,
            .tv_usec = 0};
        setsockopt(client_sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

        // Receive loop
        buffered_len = 0;
        while (1)
        {
            if (buffered_len >= rx_buf_size)
            {
                ESP_LOGW(TAG, "RX buffer overflow, resetting buffered data");
                buffered_len = 0;
            }

            int len = recv(client_sock, rx_buf + buffered_len, rx_buf_size - buffered_len, 0);
            if (len < 0)
            {
#ifdef EAGAIN
                if (errno == EAGAIN || errno == EWOULDBLOCK)
                {
                    // No data available in non-blocking mode; continue waiting
                    continue;
                }
#endif
                ESP_LOGW(TAG, "recv failed: errno %d, reconnecting...", errno);
                connection_state = 0;
                last_heartbeat_time = 0;
                break;
            }
            else if (len == 0)
            {
                ESP_LOGW(TAG, "Connection closed by server");
                connection_state = 0;
                last_heartbeat_time = 0;
                break;
            }

            buffered_len += (size_t)len;

            // Parse as many complete command frames as available.
            size_t offset = 0;
            while (buffered_len - offset >= sizeof(msg_frame_t))
            {
                msg_frame_t *hdr = (msg_frame_t *)(rx_buf + offset);
                size_t expected_size = sizeof(msg_frame_t) + hdr->length;

                if (hdr->length > MAX_PAYLOAD_SIZE)
                {
                    ESP_LOGW(TAG, "Invalid command payload length %u, dropping buffered data", hdr->length);
                    buffered_len = 0;
                    offset = 0;
                    break;
                }

                if (buffered_len - offset < expected_size)
                {
                    break;
                }

                msg_frame_t *frame = (msg_frame_t *)malloc(expected_size);
                if (frame)
                {
                    memcpy(frame, rx_buf + offset, expected_size);
                    last_heartbeat_time = esp_timer_get_time() / 1000;

                    if (xQueueSend(cmd_queue, &frame, 0) != pdTRUE)
                    {
                        // Tail-drop: discard oldest queued command to make room
                        msg_frame_t *stale = NULL;
                        if (xQueueReceive(cmd_queue, &stale, 0) == pdTRUE)
                        {
                            free(stale);
                        }
                        if (xQueueSend(cmd_queue, &frame, 0) != pdTRUE)
                        {
                            ESP_LOGW(TAG, "Command queue still full after tail-drop, dropping command");
                            free(frame);
                        }
                    }
                }

                offset += expected_size;
            }

            if (offset > 0)
            {
                if (offset < buffered_len)
                {
                    memmove(rx_buf, rx_buf + offset, buffered_len - offset);
                }
                buffered_len -= offset;
            }
        }

        // Wait before retry
        vTaskDelay(pdMS_TO_TICKS(reconnect_interval));
        retry_count++;
        reconnect_interval = (reconnect_interval * 2 > 30000) ? 30000 : reconnect_interval * 2;
    }
}
