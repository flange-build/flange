#pragma once

#include <stddef.h>
#include <stdint.h>

#include "config.h"
#include "track.h"

#define NETEASE_TOKEN_SIZE 2049
#define NETEASE_QR_URL_SIZE 513

typedef enum {
    NETEASE_QR_EXPIRED = 800,
    NETEASE_QR_WAITING = 801,
    NETEASE_QR_CONFIRMING = 802,
    NETEASE_QR_SUCCESS = 803,
    NETEASE_QR_UNKNOWN = 804,
} netease_qr_status_t;

typedef struct {
    char qr_url[NETEASE_QR_URL_SIZE];
    char uni_key[128];
    char anonymous_token[NETEASE_TOKEN_SIZE];
    char access_token[NETEASE_TOKEN_SIZE];
    char refresh_token[NETEASE_TOKEN_SIZE];
    char client_ip[64];
    int64_t expire_at;
} netease_official_session_t;

int netease_official_validate_config(const app_config_t *config,
                                     char *error, size_t error_size);
int netease_official_load_session(const app_config_t *config,
                                  netease_official_session_t *session,
                                  char *error, size_t error_size);
int netease_official_begin_login(const app_config_t *config,
                                 netease_official_session_t *session,
                                 char *error, size_t error_size);
int netease_official_poll_login(const app_config_t *config,
                                netease_official_session_t *session,
                                netease_qr_status_t *status,
                                char *error, size_t error_size);
int netease_official_save_session(const app_config_t *config,
                                  const netease_official_session_t *session,
                                  char *error, size_t error_size);
int netease_official_parse_qr_response(
    const unsigned char *response_data, size_t size,
    netease_official_session_t *session,
    char *error, size_t error_size);
int netease_official_parse_poll_response(
    const unsigned char *response_data, size_t size,
    netease_official_session_t *session, netease_qr_status_t *status,
    char *error, size_t error_size);
int netease_official_parse_client_ip(
    const unsigned char *response_data, size_t size,
    char *output, size_t output_size);
int netease_official_map_recommendations(
    const unsigned char *response_data, size_t size,
    track_list_t *tracks, char *error, size_t error_size);
size_t netease_official_map_play_urls(
    const unsigned char *response_data, size_t size,
    track_list_t *tracks, char *error, size_t error_size);
int netease_official_map_single_play_url(
    const unsigned char *response_data, size_t size,
    track_t *track, char *error, size_t error_size);
int netease_official_map_song_detail_url(
    const unsigned char *response_data, size_t size,
    track_t *track, char *error, size_t error_size);
int netease_official_load_recommendations(
    const app_config_t *config, track_list_t *tracks,
    char *error, size_t error_size);
int netease_official_resolve_track(
    const app_config_t *config, track_t *track,
    char *error, size_t error_size);
