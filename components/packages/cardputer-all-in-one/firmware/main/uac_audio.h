#pragma once

#include "esp_err.h"

/* 在 TinyUSB 安装前初始化 I2S 并启动扬声器消费任务。 */
esp_err_t uac_audio_start(void);
