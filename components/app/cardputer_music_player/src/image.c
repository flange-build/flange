#include "image.h"

#include <limits.h>
#include <stdio.h>

#define STBI_ONLY_JPEG
#define STBI_ONLY_PNG
#define STBI_NO_HDR
#define STBI_NO_LINEAR
#define STB_IMAGE_IMPLEMENTATION
#include "stb_image.h"

static uint16_t rgb565(unsigned red, unsigned green, unsigned blue)
{
    return (uint16_t)(((red & 0xf8U) << 8)
        | ((green & 0xfcU) << 3) | (blue >> 3));
}

int image_decode_cover(const unsigned char *data, size_t size,
                       uint16_t *pixels, uint16_t *theme_color,
                       char *error, size_t error_size)
{
    if (data == NULL || pixels == NULL || size == 0U
            || size > COVER_MAX_BYTES || size > INT_MAX) {
        snprintf(error, error_size, "封面数据大小无效");
        return -1;
    }
    int width = 0;
    int height = 0;
    int channels = 0;
    if (!stbi_info_from_memory(data, (int)size,
                               &width, &height, &channels)
            || width <= 0 || height <= 0) {
        snprintf(error, error_size, "封面不是合法的受限 JPEG/PNG");
        return -1;
    }
    if (width > COVER_MAX_DIMENSION || height > COVER_MAX_DIMENSION) {
        snprintf(error, error_size, "封面尺寸超过限制: %dx%d",
                 width, height);
        return -1;
    }
    unsigned char *source = stbi_load_from_memory(
        data, (int)size, &width, &height, &channels, 3
    );
    if (source == NULL) {
        snprintf(error, error_size, "封面解码失败: %.80s",
                 stbi_failure_reason());
        return -1;
    }

    uint64_t red = 0;
    uint64_t green = 0;
    uint64_t blue = 0;
    for (int y = 0; y < COVER_HEIGHT; y++) {
        int source_y = y * height / COVER_HEIGHT;
        for (int x = 0; x < COVER_WIDTH; x++) {
            int source_x = x * width / COVER_WIDTH;
            const unsigned char *color = source
                + ((size_t)source_y * (size_t)width
                   + (size_t)source_x) * 3U;
            pixels[y * COVER_WIDTH + x] = rgb565(
                color[0], color[1], color[2]
            );
            red += color[0];
            green += color[1];
            blue += color[2];
        }
    }
    stbi_image_free(source);
    if (theme_color != NULL) {
        const uint64_t count = COVER_WIDTH * COVER_HEIGHT;
        *theme_color = rgb565((unsigned)(red / count),
                              (unsigned)(green / count),
                              (unsigned)(blue / count));
    }
    return 0;
}
