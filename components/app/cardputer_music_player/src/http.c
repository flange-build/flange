#include "http.h"

#include <curl/curl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    http_response_t *response;
    size_t max_bytes;
    int overflow;
} write_context_t;

static int request_allows_redirects(const char *access_token)
{
    return access_token == NULL || access_token[0] == '\0';
}

#ifdef CARDPUTER_HTTP_TESTING
int http_test_allows_redirects(const char *access_token)
{
    return request_allows_redirects(access_token);
}
#endif

static size_t write_response(char *data, size_t size, size_t count,
                             void *opaque)
{
    write_context_t *context = opaque;
    size_t bytes = size * count;
    http_response_t *response = context->response;
    if (bytes > context->max_bytes - response->size) {
        context->overflow = 1;
        return 0;
    }
    size_t needed = response->size + bytes + 1;
    if (needed > response->capacity) {
        size_t capacity = response->capacity == 0 ? 4096 : response->capacity;
        while (capacity < needed)
            capacity *= 2;
        if (capacity > context->max_bytes + 1)
            capacity = context->max_bytes + 1;
        unsigned char *resized = realloc(response->data, capacity);
        if (resized == NULL)
            return 0;
        response->data = resized;
        response->capacity = capacity;
    }
    memcpy(response->data + response->size, data, bytes);
    response->size += bytes;
    response->data[response->size] = '\0';
    return bytes;
}

static int perform_request(const char *url, const char *access_token,
                           const char *json, size_t max_bytes,
                           long connect_timeout_ms, long timeout_ms,
                           http_response_t *response,
                           char *error, size_t error_size)
{
    memset(response, 0, sizeof(*response));
    if (url == NULL || strncmp(url, "https://", 8) != 0) {
        snprintf(error, error_size, "仅允许 HTTPS URL");
        return -1;
    }
    if (connect_timeout_ms <= 0L || timeout_ms < connect_timeout_ms) {
        snprintf(error, error_size, "HTTPS 超时参数无效");
        return -1;
    }
    CURL *curl = curl_easy_init();
    if (curl == NULL) {
        snprintf(error, error_size, "无法初始化 libcurl");
        return -1;
    }
    write_context_t context = {
        .response = response,
        .max_bytes = max_bytes,
    };
    curl_easy_setopt(curl, CURLOPT_URL, url);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_response);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &context);
    curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT_MS, connect_timeout_ms);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS, timeout_ms);
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION,
                     request_allows_redirects(access_token) ? 1L : 0L);
    curl_easy_setopt(curl, CURLOPT_MAXREDIRS,
                     request_allows_redirects(access_token) ? 3L : 0L);
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, 1L);
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYHOST, 2L);
    curl_easy_setopt(curl, CURLOPT_PROTOCOLS_STR, "https");
    curl_easy_setopt(curl, CURLOPT_REDIR_PROTOCOLS_STR, "https");
    curl_easy_setopt(curl, CURLOPT_USERAGENT,
                     "flange-cardputer-music-player/0.1");
    if (json != NULL) {
        curl_easy_setopt(curl, CURLOPT_POST, 1L);
        curl_easy_setopt(curl, CURLOPT_POSTFIELDS, json);
        curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE,
                         (long)strlen(json));
    }
    struct curl_slist *headers = NULL;
    char token_header[2304];
    if (access_token != NULL && access_token[0] != '\0') {
        int written = snprintf(token_header, sizeof(token_header),
                               "access-token: %s", access_token);
        if (written < 0 || (size_t)written >= sizeof(token_header)) {
            snprintf(error, error_size, "access token 过长");
            curl_easy_cleanup(curl);
            return -1;
        }
        headers = curl_slist_append(headers, token_header);
        if (headers == NULL) {
            snprintf(error, error_size, "无法设置 access token header");
            curl_easy_cleanup(curl);
            return -1;
        }
        curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    }
    if (json != NULL) {
        struct curl_slist *updated = curl_slist_append(
            headers, "Content-Type: application/json"
        );
        if (updated == NULL) {
            snprintf(error, error_size, "无法设置 JSON Content-Type");
            curl_slist_free_all(headers);
            curl_easy_cleanup(curl);
            return -1;
        }
        headers = updated;
        curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    }
    CURLcode result = curl_easy_perform(curl);
    if (result == CURLE_OK) {
        curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &response->status);
        char *content_type = NULL;
        curl_easy_getinfo(curl, CURLINFO_CONTENT_TYPE, &content_type);
        if (content_type != NULL) {
            snprintf(response->content_type, sizeof(response->content_type),
                     "%s", content_type);
        }
    }
    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);
    memset(token_header, 0, sizeof(token_header));

    if (context.overflow) {
        snprintf(error, error_size, "HTTPS 响应超过 %zu 字节", max_bytes);
        http_response_free(response);
        return -1;
    }
    if (result != CURLE_OK) {
        snprintf(error, error_size, "HTTPS 请求失败: %s",
                 curl_easy_strerror(result));
        http_response_free(response);
        return -1;
    }
    if (response->status < 200 || response->status >= 300) {
        snprintf(error, error_size, "HTTPS 返回状态 %ld", response->status);
        http_response_free(response);
        return -1;
    }
    return 0;
}

int http_get(const char *url, size_t max_bytes, http_response_t *response,
             char *error, size_t error_size)
{
    return perform_request(url, NULL, NULL, max_bytes, 5000L, 15000L,
                           response, error, error_size);
}

int http_get_with_timeouts(const char *url, size_t max_bytes,
                           long connect_timeout_ms, long timeout_ms,
                           http_response_t *response,
                           char *error, size_t error_size)
{
    return perform_request(url, NULL, NULL, max_bytes,
                           connect_timeout_ms, timeout_ms,
                           response, error, error_size);
}

int http_get_access_token(const char *url, const char *access_token,
                          size_t max_bytes, http_response_t *response,
                          char *error, size_t error_size)
{
    if (access_token == NULL || access_token[0] == '\0'
            || strlen(access_token) > 2048U
            || strpbrk(access_token, "\r\n") != NULL) {
        memset(response, 0, sizeof(*response));
        snprintf(error, error_size, "access token 格式无效");
        return -1;
    }
    return perform_request(url, access_token, NULL, max_bytes,
                           5000L, 15000L,
                           response, error, error_size);
}

int http_post_json(const char *url, const char *json, size_t max_bytes,
                   http_response_t *response,
                   char *error, size_t error_size)
{
    if (json == NULL || json[0] == '\0') {
        memset(response, 0, sizeof(*response));
        snprintf(error, error_size, "JSON 请求体为空");
        return -1;
    }
    return perform_request(url, NULL, json, max_bytes, 5000L, 15000L,
                           response, error, error_size);
}

void http_response_free(http_response_t *response)
{
    free(response->data);
    memset(response, 0, sizeof(*response));
}
