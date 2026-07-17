#pragma once

#include <stddef.h>

#include "track.h"

#define MANIFEST_MAX_BYTES (64 * 1024)

int manifest_parse(const char *json, size_t length, track_list_t *tracks,
                   char *error, size_t error_size);
int manifest_load_file(const char *path, track_list_t *tracks,
                       char *error, size_t error_size);
int manifest_load_source(const char *source, track_list_t *tracks,
                         char *error, size_t error_size);
