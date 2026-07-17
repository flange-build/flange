#pragma once

#include <stddef.h>

typedef struct {
    unsigned char *data;
    size_t size;
    size_t capacity;
    long status;
    char content_type[96];
} http_response_t;

int http_get(const char *url, size_t max_bytes, http_response_t *response,
             char *error, size_t error_size);
int http_get_with_timeouts(const char *url, size_t max_bytes,
                           long connect_timeout_ms, long timeout_ms,
                           http_response_t *response,
                           char *error, size_t error_size);
int http_get_access_token(const char *url, const char *access_token,
                          size_t max_bytes, http_response_t *response,
                          char *error, size_t error_size);
int http_post_json(const char *url, const char *json, size_t max_bytes,
                   http_response_t *response,
                   char *error, size_t error_size);
void http_response_free(http_response_t *response);

#ifdef CARDPUTER_HTTP_TESTING
int http_test_allows_redirects(const char *access_token);
#endif
