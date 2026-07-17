#include "font.h"

#include <stdio.h>
#include <string.h>

static const char *const font_paths[] = {
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
};

static uint32_t decode_utf8(const char **cursor)
{
    const unsigned char *text = (const unsigned char *)*cursor;
    uint32_t codepoint;
    size_t length;

    if (text[0] < 0x80) {
        codepoint = text[0];
        length = 1;
    } else if ((text[0] & 0xe0) == 0xc0 && text[1] != 0) {
        codepoint = ((uint32_t)(text[0] & 0x1f) << 6)
            | (text[1] & 0x3f);
        length = 2;
    } else if ((text[0] & 0xf0) == 0xe0
            && text[1] != 0 && text[2] != 0) {
        codepoint = ((uint32_t)(text[0] & 0x0f) << 12)
            | ((uint32_t)(text[1] & 0x3f) << 6)
            | (text[2] & 0x3f);
        length = 3;
    } else if ((text[0] & 0xf8) == 0xf0
            && text[1] != 0 && text[2] != 0 && text[3] != 0) {
        codepoint = ((uint32_t)(text[0] & 0x07) << 18)
            | ((uint32_t)(text[1] & 0x3f) << 12)
            | ((uint32_t)(text[2] & 0x3f) << 6)
            | (text[3] & 0x3f);
        length = 4;
    } else {
        codepoint = 0xfffd;
        length = 1;
    }
    *cursor += length;
    return codepoint;
}

static uint16_t blend_rgb565(uint16_t background, uint16_t foreground,
                             uint8_t alpha)
{
    unsigned br = ((background >> 11) & 0x1f) * 255 / 31;
    unsigned bg = ((background >> 5) & 0x3f) * 255 / 63;
    unsigned bb = (background & 0x1f) * 255 / 31;
    unsigned fr = ((foreground >> 11) & 0x1f) * 255 / 31;
    unsigned fg = ((foreground >> 5) & 0x3f) * 255 / 63;
    unsigned fb = (foreground & 0x1f) * 255 / 31;
    unsigned inverse = 255 - alpha;
    return rgb565(
        (uint8_t)((fr * alpha + br * inverse) / 255),
        (uint8_t)((fg * alpha + bg * inverse) / 255),
        (uint8_t)((fb * alpha + bb * inverse) / 255)
    );
}

int font_open(font_renderer_t *font)
{
    memset(font, 0, sizeof(*font));
    FT_Error error = FT_Init_FreeType(&font->library);
    if (error != 0)
        return -1;

    for (size_t i = 0; i < sizeof(font_paths) / sizeof(font_paths[0]); i++) {
        error = FT_New_Face(font->library, font_paths[i], 0, &font->face);
        if (error == 0) {
            font->ready = 1;
            fprintf(stderr, "[font] 使用 %s\n", font_paths[i]);
            return 0;
        }
    }

    FT_Done_FreeType(font->library);
    font->library = NULL;
    fprintf(stderr, "[font] 未找到中文字体，回退 ASCII bitmap\n");
    return -1;
}

void font_close(font_renderer_t *font)
{
    if (font->face != NULL)
        FT_Done_Face(font->face);
    if (font->library != NULL)
        FT_Done_FreeType(font->library);
    memset(font, 0, sizeof(*font));
}

static void draw_bitmap(framebuffer_t *fb, const FT_Bitmap *bitmap,
                        int x, int y, uint16_t color, int clip_right)
{
    for (unsigned row = 0; row < bitmap->rows; row++) {
        for (unsigned col = 0; col < bitmap->width; col++) {
            int target_x = x + (int)col;
            int target_y = y + (int)row;
            if (target_x >= clip_right || target_x < 0
                    || target_y < 0 || target_y >= fb->height)
                continue;
            uint8_t alpha = bitmap->buffer[row * (unsigned)bitmap->pitch + col];
            if (alpha == 0)
                continue;
            uint16_t *pixel = &fb->pixels[target_y * fb->width + target_x];
            *pixel = blend_rgb565(*pixel, color, alpha);
        }
    }
}

int font_draw_utf8(font_renderer_t *font, framebuffer_t *fb,
                   int x, int y, const char *text, uint16_t color,
                   int pixel_size, int max_width)
{
    if (!font->ready)
        return x;
    if (font->pixel_size != pixel_size) {
        if (FT_Set_Pixel_Sizes(font->face, 0, (FT_UInt)pixel_size) != 0)
            return x;
        font->pixel_size = pixel_size;
    }

    int pen_x = x;
    int baseline = y + pixel_size;
    int clip_right = max_width > 0 ? x + max_width : fb->width;
    const char *cursor = text;
    while (*cursor != '\0') {
        uint32_t codepoint = decode_utf8(&cursor);
        if (FT_Load_Char(font->face, codepoint, FT_LOAD_RENDER) != 0)
            continue;
        FT_GlyphSlot glyph = font->face->glyph;
        int advance = (int)(glyph->advance.x >> 6);
        if (pen_x + advance > clip_right)
            break;
        draw_bitmap(
            fb,
            &glyph->bitmap,
            pen_x + glyph->bitmap_left,
            baseline - glyph->bitmap_top,
            color,
            clip_right
        );
        pen_x += advance;
    }
    return pen_x;
}
