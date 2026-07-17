#pragma once

#include <stddef.h>

int text_ellipsize_utf8(const char *input, size_t max_codepoints,
                        char *output, size_t output_size);
