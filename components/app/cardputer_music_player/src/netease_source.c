#include "netease.h"

#include <stdio.h>
#include <string.h>

#include "http.h"
#include "manifest.h"

#define NETEASE_URL_SIZE 4096

static int response_is_json(const http_response_t *response)
{
    return response->content_type[0] == '\0'
        || strstr(response->content_type, "json") != NULL;
}

static int make_api_url(const app_config_t *config, const char *path,
                        char *url, size_t size)
{
    size_t base_length = strlen(config->netease_api_url);
    while (base_length > 0U
            && config->netease_api_url[base_length - 1U] == '/')
        base_length--;
    int written = snprintf(url, size, "%.*s%s", (int)base_length,
                           config->netease_api_url, path);
    return written > 0 && (size_t)written < size ? 0 : -1;
}

static int append_track_ids(const track_list_t *tracks,
                            char *ids, size_t size)
{
    size_t used = 0U;
    for (size_t i = 0U; i < tracks->count; i++) {
        int written = snprintf(ids + used, size - used, "%s%s",
                               i == 0U ? "" : ",", tracks->items[i].id);
        if (written < 0 || (size_t)written >= size - used)
            return -1;
        used += (size_t)written;
    }
    return 0;
}

int netease_load_playlist(const app_config_t *config,
                          track_list_t *tracks, char *error,
                          size_t error_size)
{
    if (config->netease_api_url[0] == '\0'
            || config->netease_playlist_id[0] == '\0') {
        snprintf(error, error_size,
                 "请配置网易云 API HTTPS 基址与歌单 ID");
        return -1;
    }

    char path[NETEASE_URL_SIZE];
    char url[NETEASE_URL_SIZE];
    int written = snprintf(path, sizeof(path),
                           "/playlist/track/all?id=%s&limit=%u",
                           config->netease_playlist_id, TRACK_LIST_MAX);
    if (written < 0 || (size_t)written >= sizeof(path)
            || make_api_url(config, path, url, sizeof(url)) != 0) {
        snprintf(error, error_size, "网易云歌单 URL 过长");
        return -1;
    }

    http_response_t response;
    if (http_get(url, MANIFEST_MAX_BYTES * 8U, &response,
                 error, error_size) != 0)
        return -1;
    if (!response_is_json(&response)) {
        snprintf(error, error_size, "网易云歌单 Content-Type 不是 JSON");
        http_response_free(&response);
        return -1;
    }
    int result = netease_map_playlist(
        (const char *)response.data, response.size,
        tracks, error, error_size
    );
    http_response_free(&response);
    if (result != 0)
        return -1;

    char ids[TRACK_LIST_MAX * TRACK_ID_SIZE];
    if (append_track_ids(tracks, ids, sizeof(ids)) != 0) {
        snprintf(error, error_size, "网易云歌曲 ID 列表过长");
        return -1;
    }
    written = snprintf(path, sizeof(path),
                       "/song/url/v1?id=%s&level=standard&unblock=false",
                       ids);
    if (written < 0 || (size_t)written >= sizeof(path)
            || make_api_url(config, path, url, sizeof(url)) != 0) {
        snprintf(error, error_size, "网易云播放地址 URL 过长");
        return -1;
    }
    if (http_get(url, MANIFEST_MAX_BYTES * 4U, &response,
                 error, error_size) != 0) {
        fprintf(stderr, "[netease] 播放地址不可用，保留歌单元数据: %s\n",
                error);
        error[0] = '\0';
        return 0;
    }
    if (!response_is_json(&response)) {
        fprintf(stderr, "[netease] 播放地址 Content-Type 不是 JSON\n");
        http_response_free(&response);
        error[0] = '\0';
        return 0;
    }
    size_t mapped = netease_map_urls(
        (const char *)response.data, response.size,
        tracks, error, error_size
    );
    http_response_free(&response);
    fprintf(stderr, "[netease] 可播放歌曲 %zu/%zu 首\n",
            mapped, tracks->count);
    error[0] = '\0';
    return 0;
}
