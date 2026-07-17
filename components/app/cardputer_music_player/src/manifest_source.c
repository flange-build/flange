#include "manifest.h"

#include <stdio.h>
#include <string.h>

#include "http.h"

int manifest_load_source(const char *source, track_list_t *tracks,
                         char *error, size_t error_size)
{
    if (source == NULL || source[0] == '\0') {
        snprintf(error, error_size, "Manifest source 为空");
        return -1;
    }
    if (strncmp(source, "https://", 8) != 0) {
        const char *path = strncmp(source, "file://", 7) == 0
            ? source + 7 : source;
        if (path[0] != '/') {
            snprintf(error, error_size, "本地 Manifest 必须使用绝对路径");
            return -1;
        }
        return manifest_load_file(path, tracks, error, error_size);
    }

    http_response_t response;
    if (http_get(source, MANIFEST_MAX_BYTES, &response,
                 error, error_size) != 0)
        return -1;
    if (response.content_type[0] != '\0'
            && strstr(response.content_type, "json") == NULL) {
        snprintf(error, error_size, "Manifest Content-Type 不是 JSON");
        http_response_free(&response);
        return -1;
    }
    int result = manifest_parse((const char *)response.data,
                                response.size, tracks,
                                error, error_size);
    http_response_free(&response);
    return result;
}
