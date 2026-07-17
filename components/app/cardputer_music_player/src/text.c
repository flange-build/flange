#include "text.h"

#include <string.h>

static size_t utf8_character_size(unsigned char value)
{
    if (value < 0x80U)
        return 1U;
    if ((value & 0xe0U) == 0xc0U)
        return 2U;
    if ((value & 0xf0U) == 0xe0U)
        return 3U;
    if ((value & 0xf8U) == 0xf0U)
        return 4U;
    return 1U;
}

int text_ellipsize_utf8(const char *input, size_t max_codepoints,
                        char *output, size_t output_size)
{
    static const char ellipsis[] = "…";
    if (input == NULL || output == NULL || output_size == 0U
            || max_codepoints < 2U)
        return -1;
    size_t input_length = strlen(input);
    size_t cursor = 0;
    size_t count = 0;
    while (cursor < input_length && count < max_codepoints) {
        size_t character_size = utf8_character_size(
            (unsigned char)input[cursor]
        );
        if (character_size > input_length - cursor)
            character_size = 1U;
        cursor += character_size;
        count++;
    }
    if (cursor == input_length) {
        if (input_length + 1U > output_size)
            return -1;
        memcpy(output, input, input_length + 1U);
        return 0;
    }

    cursor = 0;
    count = 0;
    while (cursor < input_length && count + 1U < max_codepoints) {
        size_t character_size = utf8_character_size(
            (unsigned char)input[cursor]
        );
        if (character_size > input_length - cursor)
            character_size = 1U;
        if (cursor + character_size + sizeof(ellipsis) > output_size)
            return -1;
        cursor += character_size;
        count++;
    }
    memcpy(output, input, cursor);
    memcpy(output + cursor, ellipsis, sizeof(ellipsis));
    return 1;
}
