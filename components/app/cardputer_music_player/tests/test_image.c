#include <assert.h>
#include <stdio.h>
#include <stdlib.h>

#include "image.h"

int main(int argc, char **argv)
{
    assert(argc == 2);
    FILE *file = fopen(argv[1], "rb");
    assert(file != NULL);
    assert(fseek(file, 0, SEEK_END) == 0);
    long length = ftell(file);
    assert(length > 0 && (unsigned long)length <= COVER_MAX_BYTES);
    rewind(file);
    unsigned char *data = malloc((size_t)length);
    assert(data != NULL);
    assert(fread(data, 1, (size_t)length, file) == (size_t)length);
    fclose(file);

    uint16_t pixels[COVER_WIDTH * COVER_HEIGHT] = {0};
    uint16_t theme = 0;
    char error[160] = {0};
    assert(image_decode_cover(data, (size_t)length, pixels, &theme,
                              error, sizeof(error)) == 0);
    assert(theme != 0);
    int has_detail = 0;
    for (size_t i = 1; i < COVER_WIDTH * COVER_HEIGHT; i++) {
        if (pixels[i] != pixels[0]) {
            has_detail = 1;
            break;
        }
    }
    assert(has_detail);
    free(data);
    puts("image tests passed");
    return 0;
}
