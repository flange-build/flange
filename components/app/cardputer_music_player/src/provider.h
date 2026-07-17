#pragma once

#include <stddef.h>

#include "config.h"
#include "track.h"

/*
 * 将抖音官方榜单或用户 broker 的响应归一化为 Track。
 * broker 也可直接返回统一 Manifest 的 {"tracks": [...]} 契约。
 */
int provider_map_douyin(const char *json, size_t length,
                        track_list_t *tracks, char *error,
                        size_t error_size);
int provider_load_douyin(const app_config_t *config, track_list_t *tracks,
                         char *error, size_t error_size);
size_t provider_merge_resolutions(track_list_t *tracks,
                                  const track_list_t *resolutions);
int provider_apply_resolver(const app_config_t *config,
                            track_list_t *tracks,
                            char *error, size_t error_size);
