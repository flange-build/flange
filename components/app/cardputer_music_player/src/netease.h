#pragma once

#include <stddef.h>

#include "config.h"
#include "track.h"

int netease_map_playlist(const char *json, size_t length,
                         track_list_t *tracks, char *error,
                         size_t error_size);
size_t netease_map_urls(const char *json, size_t length,
                        track_list_t *tracks, char *error,
                        size_t error_size);
int netease_load_playlist(const app_config_t *config,
                          track_list_t *tracks, char *error,
                          size_t error_size);
