#include "iot_agent.h"
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "driver/gpio.h"
#include "driver/adc.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_timer.h"

static const char *TAG = "gpio_mgr";
static adc_oneshot_unit_handle_t adc_handle = NULL;

// Initialize ADC
static void init_adc(void)
{
    if (!adc_handle)
    {
        adc_oneshot_unit_init_cfg_t init_config = {
            .unit_id = ADC_UNIT_1,
            .ulp_mode = ADC_ULP_MODE_DISABLE,
        };
        ESP_ERROR_CHECK(adc_oneshot_new_unit(&init_config, &adc_handle));

        adc_oneshot_chan_cfg_t config = {
            .bitwidth = ADC_BITWIDTH_12,
            .atten = ADC_ATTEN_DB_11,
        };
        // Configure channel 0 (GPIO 1)
        adc_oneshot_config_channel(adc_handle, ADC_CHANNEL_0, &config);
    }
}

// ADC sampling function
uint16_t adc_read_sample(uint8_t gpio, uint8_t samples)
{
    if (!adc_handle)
    {
        init_adc();
    }

    uint32_t sum = 0;
    uint8_t count = samples > 0 ? samples : 1;

    // Map GPIO to ADC channel (simplified - only GPIO 1-4 supported)
    adc_channel_t channel = ADC_CHANNEL_0;
    int adc_raw = 0;

    for (int i = 0; i < count; i++)
    {
        adc_oneshot_read(adc_handle, channel, &adc_raw);
        sum += adc_raw;
    }

    uint16_t avg = sum / count;
    ESP_LOGD(TAG, "ADC GPIO %d: raw=%d, samples=%d", gpio, avg, count);
    return avg;
}

// GPIO ISR handler for edge detection
void gpio_isr_handler(void *arg)
{
    int gpio_num = (int)(uintptr_t)arg;
    uint8_t level = gpio_get_level(gpio_num);

    uint8_t edge_type = level ? 1 : 2; // 1=rising, 2=falling
    int64_t timestamp = esp_timer_get_time();

    event_gpio_edge_t event = {
        .gpio = gpio_num,
        .edge_type = edge_type,
        .timestamp_us = timestamp};

    // Send event (from ISR, so use FromISR variant if available)
    send_event(EVENT_GPIO_EDGE, &event, sizeof(event_gpio_edge_t));

    gpio_table[gpio_num].value = level;
    gpio_table[gpio_num].last_ts = timestamp;
}
