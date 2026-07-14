#include "uac_audio.h"

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "driver/i2s_std.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "tusb.h"

#include "cardputer_pins.h"
#include "usb_descriptors.h"

#define UAC_FRAME_SAMPLES (UAC_SAMPLE_RATE / 1000)
#define UAC_FRAME_BYTES (UAC_FRAME_SAMPLES * UAC_BYTES_PER_SAMPLE)
#define UAC_TASK_STACK_SIZE 3072
#define UAC_TASK_PRIORITY 6

_Static_assert(UAC_SAMPLE_RATE % 1000 == 0, "UAC 采样率必须产生整数 samples/ms");
_Static_assert(UAC_FRAME_BYTES == UAC_EP_OUT_SIZE, "UAC 帧大小必须等于 endpoint 大小");

static const char *TAG = "uac_audio";
static i2s_chan_handle_t tx_channel;
static volatile bool streaming;

static void audio_task(void *arg)
{
    int16_t samples[UAC_FRAME_SAMPLES];

    (void)arg;

    while (true) {
        size_t bytes_written = 0;
        uint16_t bytes_read = 0;

        memset(samples, 0, sizeof(samples));
        if (streaming && tud_mounted())
            bytes_read = tud_audio_read(samples, sizeof(samples));

        if (bytes_read < sizeof(samples))
            memset((uint8_t *)samples + bytes_read, 0, sizeof(samples) - bytes_read);

        esp_err_t err = i2s_channel_write(tx_channel, samples, sizeof(samples),
                                          &bytes_written, portMAX_DELAY);
        if (err != ESP_OK || bytes_written != sizeof(samples)) {
            ESP_LOGE(TAG, "I2S 写入失败: err=%s bytes=%u",
                     esp_err_to_name(err), (unsigned int)bytes_written);
            vTaskDelay(pdMS_TO_TICKS(1));
        }
    }
}

esp_err_t uac_audio_start(void)
{
    i2s_chan_config_t channel_config = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_AUTO,
                                                                  I2S_ROLE_MASTER);
    i2s_std_config_t std_config = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(UAC_SAMPLE_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT,
                                                        I2S_SLOT_MODE_MONO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = PIN_SPK_BCLK,
            .ws = PIN_SPK_WS,
            .dout = PIN_SPK_DOUT,
            .din = I2S_GPIO_UNUSED,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv = false,
            },
        },
    };

    channel_config.dma_desc_num = 4;
    channel_config.dma_frame_num = UAC_FRAME_SAMPLES;

    esp_err_t err = i2s_new_channel(&channel_config, &tx_channel, NULL);
    if (err != ESP_OK)
        return err;

    err = i2s_channel_init_std_mode(tx_channel, &std_config);
    if (err != ESP_OK)
        goto cleanup;

    err = i2s_channel_enable(tx_channel);
    if (err != ESP_OK)
        goto cleanup;

    if (xTaskCreate(audio_task, "uac_audio", UAC_TASK_STACK_SIZE, NULL,
                    UAC_TASK_PRIORITY, NULL) != pdPASS) {
        err = ESP_ERR_NO_MEM;
        goto cleanup;
    }

    ESP_LOGI(TAG, "UAC1 speaker ready: mono %d Hz / 16 bit", UAC_SAMPLE_RATE);
    return ESP_OK;

cleanup:
    if (tx_channel != NULL) {
        i2s_del_channel(tx_channel);
        tx_channel = NULL;
    }
    return err;
}

bool tud_audio_set_itf_cb(uint8_t rhport, tusb_control_request_t const *request)
{
    uint8_t interface_number = tu_u16_low(request->wIndex);
    uint8_t alternate_setting = tu_u16_low(request->wValue);

    (void)rhport;

    if (interface_number == ITF_NUM_AUDIO_STREAMING)
        streaming = alternate_setting == 1;

    return true;
}

bool tud_audio_set_itf_close_ep_cb(uint8_t rhport,
                                   tusb_control_request_t const *request)
{
    uint8_t interface_number = tu_u16_low(request->wIndex);

    (void)rhport;

    if (interface_number == ITF_NUM_AUDIO_STREAMING) {
        streaming = false;
        tud_audio_clear_ep_out_ff();
    }

    return true;
}

bool tud_audio_get_req_ep_cb(uint8_t rhport, tusb_control_request_t const *request)
{
    static uint8_t sample_rate[] = {
        UAC_SAMPLE_RATE & 0xff,
        (UAC_SAMPLE_RATE >> 8) & 0xff,
        (UAC_SAMPLE_RATE >> 16) & 0xff,
    };
    uint8_t control_selector = tu_u16_high(request->wValue);

    if (control_selector != AUDIO10_EP_CTRL_SAMPLING_FREQ ||
        request->bRequest != AUDIO10_CS_REQ_GET_CUR)
        return false;

    return tud_audio_buffer_and_schedule_control_xfer(rhport, request, sample_rate,
                                                       sizeof(sample_rate));
}

bool tud_audio_set_req_ep_cb(uint8_t rhport, tusb_control_request_t const *request,
                            uint8_t *buffer)
{
    uint8_t control_selector = tu_u16_high(request->wValue);
    uint32_t sample_rate;

    (void)rhport;

    if (control_selector != AUDIO10_EP_CTRL_SAMPLING_FREQ ||
        request->bRequest != AUDIO10_CS_REQ_SET_CUR || request->wLength != 3)
        return false;

    sample_rate = (uint32_t)buffer[0] |
                  ((uint32_t)buffer[1] << 8) |
                  ((uint32_t)buffer[2] << 16);
    return sample_rate == UAC_SAMPLE_RATE;
}
