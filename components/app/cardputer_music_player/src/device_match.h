#pragma once

#include <stddef.h>

int device_match_gud_framebuffer(const char *name);
int device_match_cardputer_input(const char *name, int supports_ev_key);
int device_match_cardputer_pcm(const char *name, const char *description,
                               const char *io_id);
int device_make_plughw(const char *hint_name, char *device, size_t size);
