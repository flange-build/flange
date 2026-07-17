#pragma once

#include <stddef.h>

#define CONFIG_MAX_BYTES (16U * 1024U)
#define CONFIG_URL_SIZE 768
#define CONFIG_PATH_SIZE 256

typedef struct {
    char provider[48];
    char manifest_url[CONFIG_URL_SIZE];
    char douyin_api_url[CONFIG_URL_SIZE];
    char douyin_broker_url[CONFIG_URL_SIZE];
    char douyin_access_token_file[CONFIG_PATH_SIZE];
    char resolver_url[CONFIG_URL_SIZE];
    char netease_api_url[CONFIG_URL_SIZE];
    char netease_playlist_id[32];
    char netease_app_id[96];
    char netease_private_key_file[CONFIG_PATH_SIZE];
    char netease_session_file[CONFIG_PATH_SIZE];
    char framebuffer_name[64];
    char input_name[96];
    char alsa_device[96];
    char visualizer[24];
    unsigned fps;
} app_config_t;

void config_defaults(app_config_t *config);
int config_parse(const char *json, size_t length, app_config_t *config,
                 char *error, size_t error_size);
int config_load_file(const char *path, app_config_t *config,
                     char *error, size_t error_size);
