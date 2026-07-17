#pragma once

#include <stddef.h>
#include <stdint.h>

#define TRACK_ID_SIZE 96
#define TRACK_SOURCE_SIZE 24
#define TRACK_TITLE_SIZE 160
#define TRACK_ARTIST_SIZE 120
#define TRACK_URL_SIZE 768
#define TRACK_LIST_MAX 32

typedef struct {
    char id[TRACK_ID_SIZE];
    char source[TRACK_SOURCE_SIZE];
    unsigned rank;
    char title[TRACK_TITLE_SIZE];
    char artist[TRACK_ARTIST_SIZE];
    uint64_t duration_ms;
    char cover_url[TRACK_URL_SIZE];
    char audio_url[TRACK_URL_SIZE];
    char share_url[TRACK_URL_SIZE];
    int audio_resolved;
} track_t;

typedef struct {
    track_t items[TRACK_LIST_MAX];
    size_t count;
} track_list_t;

int track_audio_url_is_allowed(const char *url);
