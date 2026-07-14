#include "uac_audio.h"

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "driver/gpio.h"
#include "driver/i2s_pdm.h"
#include "driver/i2s_std.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "tusb.h"

#include "cardputer_pins.h"
#include "usb_descriptors.h"

#define UAC_FRAME_SAMPLES (UAC_SAMPLE_RATE / 1000)
#define UAC_FRAME_BYTES (UAC_FRAME_SAMPLES * UAC_BYTES_PER_SAMPLE)
#define UAC_TASK_STACK_SIZE 4096
#define UAC_TASK_PRIORITY 6

_Static_assert(UAC_SAMPLE_RATE % 1000 == 0, "UAC 采样率必须产生整数 samples/ms");
_Static_assert(UAC_FRAME_BYTES == UAC_EP_OUT_SIZE, "扬声器帧必须等于 OUT endpoint 大小");
_Static_assert(UAC_FRAME_BYTES == UAC_EP_IN_SIZE, "麦克风帧必须等于 IN endpoint 大小");

typedef enum {
    AUDIO_MODE_IDLE,
    AUDIO_MODE_SPEAKER,
    AUDIO_MODE_MICROPHONE,
} audio_mode_t;

static const char *TAG = "uac_audio";
static i2s_chan_handle_t tx_channel;
static i2s_chan_handle_t rx_channel;
static portMUX_TYPE state_lock = portMUX_INITIALIZER_UNLOCKED;
static bool speaker_requested;
static bool microphone_requested;
static audio_mode_t requested_mode;

static i2s_std_gpio_config_t speaker_gpio_config(void)
{
    i2s_std_gpio_config_t config = {
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
    };

    return config;
}

static i2s_pdm_rx_gpio_config_t microphone_gpio_config(void)
{
    i2s_pdm_rx_gpio_config_t config = {
        .clk = PIN_SPK_WS,
        .dins = {
            PIN_MIC_DATA,
            I2S_GPIO_UNUSED,
            I2S_GPIO_UNUSED,
            I2S_GPIO_UNUSED,
        },
        .invert_flags = {
            .clk_inv = false,
        },
    };

    return config;
}

static audio_mode_t get_requested_mode(void)
{
    audio_mode_t mode;

    portENTER_CRITICAL(&state_lock);
    mode = requested_mode;
    portEXIT_CRITICAL(&state_lock);
    return mode;
}

static void update_stream_request(uint8_t interface_number, bool enabled)
{
    portENTER_CRITICAL(&state_lock);

    if (interface_number == ITF_NUM_AUDIO_STREAMING_OUT) {
        speaker_requested = enabled;
        if (enabled)
            requested_mode = AUDIO_MODE_SPEAKER;
        else if (requested_mode == AUDIO_MODE_SPEAKER)
            requested_mode = microphone_requested ? AUDIO_MODE_MICROPHONE : AUDIO_MODE_IDLE;
    } else if (interface_number == ITF_NUM_AUDIO_STREAMING_IN) {
        microphone_requested = enabled;
        if (enabled)
            requested_mode = AUDIO_MODE_MICROPHONE;
        else if (requested_mode == AUDIO_MODE_MICROPHONE)
            requested_mode = speaker_requested ? AUDIO_MODE_SPEAKER : AUDIO_MODE_IDLE;
    }

    portEXIT_CRITICAL(&state_lock);
}

static esp_err_t switch_audio_mode(audio_mode_t *active_mode, audio_mode_t target_mode)
{
    esp_err_t err;

    if (*active_mode == target_mode)
        return ESP_OK;

    if (*active_mode == AUDIO_MODE_SPEAKER) {
        err = i2s_channel_disable(tx_channel);
        if (err != ESP_OK)
            return err;
        tud_audio_clear_ep_out_ff();
    } else if (*active_mode == AUDIO_MODE_MICROPHONE) {
        err = i2s_channel_disable(rx_channel);
        if (err != ESP_OK)
            return err;
        tud_audio_clear_ep_in_ff();
    }

    *active_mode = AUDIO_MODE_IDLE;
    gpio_reset_pin(PIN_SPK_WS);

    if (target_mode == AUDIO_MODE_SPEAKER) {
        i2s_std_gpio_config_t gpio_config = speaker_gpio_config();

        tud_audio_clear_ep_out_ff();
        err = i2s_channel_reconfig_std_gpio(tx_channel, &gpio_config);
        if (err == ESP_OK)
            err = i2s_channel_enable(tx_channel);
    } else if (target_mode == AUDIO_MODE_MICROPHONE) {
        i2s_pdm_rx_gpio_config_t gpio_config = microphone_gpio_config();

        tud_audio_clear_ep_in_ff();
        err = i2s_channel_reconfig_pdm_rx_gpio(rx_channel, &gpio_config);
        if (err == ESP_OK)
            err = i2s_channel_enable(rx_channel);
    } else {
        return ESP_OK;
    }

    if (err == ESP_OK) {
        *active_mode = target_mode;
        ESP_LOGI(TAG, "音频方向切换为 %s",
                 target_mode == AUDIO_MODE_SPEAKER ? "speaker" : "microphone");
    }

    return err;
}

static void process_speaker_frame(int16_t *samples)
{
    size_t bytes_written = 0;
    uint16_t bytes_read = 0;

    memset(samples, 0, UAC_FRAME_BYTES);
    if (tud_mounted())
        bytes_read = tud_audio_read(samples, UAC_FRAME_BYTES);

    if (bytes_read < UAC_FRAME_BYTES)
        memset((uint8_t *)samples + bytes_read, 0, UAC_FRAME_BYTES - bytes_read);

    esp_err_t err = i2s_channel_write(tx_channel, samples, UAC_FRAME_BYTES,
                                      &bytes_written, portMAX_DELAY);
    if (err != ESP_OK || bytes_written != UAC_FRAME_BYTES) {
        ESP_LOGE(TAG, "I2S 写入失败: err=%s bytes=%u",
                 esp_err_to_name(err), (unsigned int)bytes_written);
    }
}

static void process_microphone_frame(int16_t *samples)
{
    size_t bytes_read = 0;

    esp_err_t err = i2s_channel_read(rx_channel, samples, UAC_FRAME_BYTES,
                                     &bytes_read, portMAX_DELAY);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "PDM 读取失败: %s", esp_err_to_name(err));
        return;
    }

    if (bytes_read < UAC_FRAME_BYTES)
        memset((uint8_t *)samples + bytes_read, 0, UAC_FRAME_BYTES - bytes_read);

    if (tud_mounted())
        tud_audio_write(samples, UAC_FRAME_BYTES);
}

static void audio_task(void *arg)
{
    int16_t samples[UAC_FRAME_SAMPLES];
    audio_mode_t active_mode = AUDIO_MODE_IDLE;

    (void)arg;

    while (true) {
        audio_mode_t target_mode = tud_mounted() ? get_requested_mode() : AUDIO_MODE_IDLE;
        esp_err_t err = switch_audio_mode(&active_mode, target_mode);

        if (err != ESP_OK) {
            ESP_LOGE(TAG, "音频方向切换失败: %s", esp_err_to_name(err));
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }

        if (active_mode == AUDIO_MODE_SPEAKER)
            process_speaker_frame(samples);
        else if (active_mode == AUDIO_MODE_MICROPHONE)
            process_microphone_frame(samples);
        else
            vTaskDelay(pdMS_TO_TICKS(1));
    }
}

esp_err_t uac_audio_start(void)
{
    i2s_chan_config_t tx_channel_config =
        I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_1, I2S_ROLE_MASTER);
    i2s_chan_config_t rx_channel_config =
        I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    i2s_std_config_t std_config = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(UAC_SAMPLE_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT,
                                                        I2S_SLOT_MODE_MONO),
        .gpio_cfg = speaker_gpio_config(),
    };
    i2s_pdm_rx_config_t pdm_config = {
        .clk_cfg = I2S_PDM_RX_CLK_DEFAULT_CONFIG(UAC_SAMPLE_RATE),
        .slot_cfg = I2S_PDM_RX_SLOT_PCM_FMT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT,
                                                           I2S_SLOT_MODE_MONO),
        .gpio_cfg = microphone_gpio_config(),
    };
    esp_err_t err;

    tx_channel_config.dma_desc_num = 4;
    tx_channel_config.dma_frame_num = UAC_FRAME_SAMPLES;
    rx_channel_config.dma_desc_num = 4;
    rx_channel_config.dma_frame_num = UAC_FRAME_SAMPLES;
    pdm_config.slot_cfg.slot_mask = I2S_PDM_RX_LINE0_SLOT_LEFT;

    err = i2s_new_channel(&tx_channel_config, &tx_channel, NULL);
    if (err != ESP_OK)
        return err;

    err = i2s_channel_init_std_mode(tx_channel, &std_config);
    if (err != ESP_OK)
        goto cleanup;

    err = i2s_new_channel(&rx_channel_config, NULL, &rx_channel);
    if (err != ESP_OK)
        goto cleanup;

    err = i2s_channel_init_pdm_rx_mode(rx_channel, &pdm_config);
    if (err != ESP_OK)
        goto cleanup;

    gpio_reset_pin(PIN_SPK_WS);

    if (xTaskCreate(audio_task, "uac_audio", UAC_TASK_STACK_SIZE, NULL,
                    UAC_TASK_PRIORITY, NULL) != pdPASS) {
        err = ESP_ERR_NO_MEM;
        goto cleanup;
    }

    ESP_LOGI(TAG, "UAC1 half-duplex audio ready: mono %d Hz / 16 bit", UAC_SAMPLE_RATE);
    return ESP_OK;

cleanup:
    if (rx_channel != NULL) {
        i2s_del_channel(rx_channel);
        rx_channel = NULL;
    }
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

    update_stream_request(interface_number, alternate_setting == 1);
    return true;
}

bool tud_audio_set_itf_close_ep_cb(uint8_t rhport,
                                   tusb_control_request_t const *request)
{
    uint8_t interface_number = tu_u16_low(request->wIndex);

    (void)rhport;

    update_stream_request(interface_number, false);
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
