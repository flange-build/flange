#include "framebuffer.h"

#include <errno.h>
#include <fcntl.h>
#include <linux/fb.h>
#include <linux/kd.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>

#include "device_match.h"

static int read_text_file(const char *path, char *buffer, size_t size)
{
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0)
        return -1;
    ssize_t got = read(fd, buffer, size - 1);
    close(fd);
    if (got < 0)
        return -1;
    buffer[got] = '\0';
    return 0;
}

static int find_gud_framebuffer(char *path, size_t size)
{
    for (int index = 0; index < 16; index++) {
        char name_path[96];
        char name[64];
        snprintf(name_path, sizeof(name_path),
                 "/sys/class/graphics/fb%d/name", index);
        if (read_text_file(name_path, name, sizeof(name)) != 0)
            continue;
        if (!device_match_gud_framebuffer(name))
            continue;
        snprintf(path, size, "/dev/fb%d", index);
        return 0;
    }
    return -1;
}

int framebuffer_open_gud(framebuffer_t *fb)
{
    struct fb_fix_screeninfo fix;
    struct fb_var_screeninfo var;

    memset(fb, 0, sizeof(*fb));
    fb->fd = -1;
    fb->tty_fd = -1;

    if (find_gud_framebuffer(fb->path, sizeof(fb->path)) != 0) {
        fprintf(stderr, "[display] 未找到 guddrmfb framebuffer\n");
        return -1;
    }

    fb->fd = open(fb->path, O_RDWR | O_CLOEXEC);
    if (fb->fd < 0) {
        fprintf(stderr, "[display] 无法打开 %s: %s\n",
                fb->path, strerror(errno));
        return -1;
    }
    if (ioctl(fb->fd, FBIOGET_FSCREENINFO, &fix) != 0
            || ioctl(fb->fd, FBIOGET_VSCREENINFO, &var) != 0) {
        fprintf(stderr, "[display] 无法读取 framebuffer 信息: %s\n",
                strerror(errno));
        framebuffer_close(fb);
        return -1;
    }
    if (var.xres != UI_WIDTH || var.yres != UI_HEIGHT
            || var.bits_per_pixel != 16) {
        fprintf(stderr,
                "[display] GUD 模式不兼容: %ux%u %ubpp，期望 %dx%d 16bpp\n",
                var.xres, var.yres, var.bits_per_pixel, UI_WIDTH, UI_HEIGHT);
        framebuffer_close(fb);
        return -1;
    }
    size_t row_bytes = (size_t)UI_WIDTH * sizeof(uint16_t);
    size_t required_map = (size_t)fix.line_length * (size_t)var.yres;
    if (var.red.offset != 11 || var.red.length != 5
            || var.green.offset != 5 || var.green.length != 6
            || var.blue.offset != 0 || var.blue.length != 5
            || var.transp.length != 0
            || fix.line_length < row_bytes
            || fix.smem_len < required_map) {
        fprintf(stderr,
                "[display] GUD framebuffer 不是有效的 RGB565 映射:"
                " stride=%u smem=%u\n",
                fix.line_length, fix.smem_len);
        framebuffer_close(fb);
        return -1;
    }

    fb->width = (int)var.xres;
    fb->height = (int)var.yres;
    fb->stride = (int)fix.line_length;
    fb->map_size = (size_t)fix.smem_len;
    fb->map = mmap(NULL, fb->map_size, PROT_READ | PROT_WRITE,
                   MAP_SHARED, fb->fd, 0);
    if (fb->map == MAP_FAILED) {
        fb->map = NULL;
        fprintf(stderr, "[display] mmap %s 失败: %s\n",
                fb->path, strerror(errno));
        framebuffer_close(fb);
        return -1;
    }

    fb->tty_fd = open("/dev/tty1", O_RDWR | O_CLOEXEC | O_NOCTTY);
    if (fb->tty_fd >= 0) {
        if (ioctl(fb->tty_fd, KDGETMODE, &fb->tty_mode) == 0)
            (void)ioctl(fb->tty_fd, KDSETMODE, KD_GRAPHICS);
    }

    fprintf(stderr, "[display] 使用 %s，%dx%d RGB565 stride=%d\n",
            fb->path, fb->width, fb->height, fb->stride);
    return 0;
}

int framebuffer_restore_tty(void)
{
    int tty_fd = open("/dev/tty1", O_RDWR | O_CLOEXEC | O_NOCTTY);
    if (tty_fd < 0) {
        fprintf(stderr, "[display] 无法打开 /dev/tty1: %s\n",
                strerror(errno));
        return -1;
    }
    int result = ioctl(tty_fd, KDSETMODE, KD_TEXT);
    if (result != 0) {
        fprintf(stderr, "[display] 无法恢复 tty 文本模式: %s\n",
                strerror(errno));
    }
    close(tty_fd);
    return result;
}

void framebuffer_close(framebuffer_t *fb)
{
    if (fb->tty_fd >= 0) {
        (void)ioctl(fb->tty_fd, KDSETMODE,
                    fb->tty_mode == KD_GRAPHICS ? KD_TEXT : fb->tty_mode);
        close(fb->tty_fd);
        fb->tty_fd = -1;
    }
    if (fb->map != NULL) {
        munmap(fb->map, fb->map_size);
        fb->map = NULL;
    }
    if (fb->fd >= 0) {
        close(fb->fd);
        fb->fd = -1;
    }
}

void framebuffer_present(framebuffer_t *fb)
{
    for (int y = 0; y < fb->height; y++) {
        memcpy(fb->map + (size_t)y * (size_t)fb->stride,
               &fb->pixels[y * fb->width],
               (size_t)fb->width * sizeof(uint16_t));
    }
}

void gfx_clear(framebuffer_t *fb, uint16_t color)
{
    for (size_t i = 0; i < (size_t)UI_WIDTH * UI_HEIGHT; i++)
        fb->pixels[i] = color;
}

void gfx_pixel(framebuffer_t *fb, int x, int y, uint16_t color)
{
    if (x < 0 || x >= fb->width || y < 0 || y >= fb->height)
        return;
    fb->pixels[y * fb->width + x] = color;
}

void gfx_rect(framebuffer_t *fb, int x, int y, int w, int h, uint16_t color)
{
    if (x < 0) {
        w += x;
        x = 0;
    }
    if (y < 0) {
        h += y;
        y = 0;
    }
    if (x + w > fb->width)
        w = fb->width - x;
    if (y + h > fb->height)
        h = fb->height - y;
    if (w <= 0 || h <= 0)
        return;

    for (int row = 0; row < h; row++) {
        uint16_t *dst = &fb->pixels[(y + row) * fb->width + x];
        for (int col = 0; col < w; col++)
            dst[col] = color;
    }
}

void gfx_line(framebuffer_t *fb, int x0, int y0, int x1, int y1,
              uint16_t color)
{
    int dx = abs(x1 - x0);
    int sx = x0 < x1 ? 1 : -1;
    int dy = -abs(y1 - y0);
    int sy = y0 < y1 ? 1 : -1;
    int err = dx + dy;

    for (;;) {
        gfx_pixel(fb, x0, y0, color);
        if (x0 == x1 && y0 == y1)
            break;
        int twice = 2 * err;
        if (twice >= dy) {
            err += dy;
            x0 += sx;
        }
        if (twice <= dx) {
            err += dx;
            y0 += sy;
        }
    }
}

/* 仅承载小屏 UI 所需的 ASCII 5x7 字形；每项是从上到下的 5-bit 行。 */
static const uint8_t *glyph_rows(char ch)
{
    static const uint8_t blank[7] = {0};
    static const uint8_t letters[26][7] = {
        {14,17,17,31,17,17,17}, {30,17,17,30,17,17,30},
        {14,17,16,16,16,17,14}, {30,17,17,17,17,17,30},
        {31,16,16,30,16,16,31}, {31,16,16,30,16,16,16},
        {14,17,16,23,17,17,15}, {17,17,17,31,17,17,17},
        {31,4,4,4,4,4,31}, {7,2,2,2,18,18,12},
        {17,18,20,24,20,18,17}, {16,16,16,16,16,16,31},
        {17,27,21,21,17,17,17}, {17,25,21,19,17,17,17},
        {14,17,17,17,17,17,14}, {30,17,17,30,16,16,16},
        {14,17,17,17,21,18,13}, {30,17,17,30,20,18,17},
        {15,16,16,14,1,1,30}, {31,4,4,4,4,4,4},
        {17,17,17,17,17,17,14}, {17,17,17,17,17,10,4},
        {17,17,17,21,21,21,10}, {17,17,10,4,10,17,17},
        {17,17,10,4,4,4,4}, {31,1,2,4,8,16,31}
    };
    static const uint8_t digits[10][7] = {
        {14,17,19,21,25,17,14}, {4,12,4,4,4,4,14},
        {14,17,1,2,4,8,31}, {30,1,1,14,1,1,30},
        {2,6,10,18,31,2,2}, {31,16,16,30,1,1,30},
        {14,16,16,30,17,17,14}, {31,1,2,4,8,8,8},
        {14,17,17,14,17,17,14}, {14,17,17,15,1,1,14}
    };
    static const uint8_t colon[7] = {0,4,4,0,4,4,0};
    static const uint8_t dash[7] = {0,0,0,31,0,0,0};
    static const uint8_t dot[7] = {0,0,0,0,0,4,4};

    if (ch >= 'a' && ch <= 'z')
        ch = (char)(ch - 'a' + 'A');
    if (ch >= 'A' && ch <= 'Z')
        return letters[ch - 'A'];
    if (ch >= '0' && ch <= '9')
        return digits[ch - '0'];
    if (ch == ':')
        return colon;
    if (ch == '-')
        return dash;
    if (ch == '.')
        return dot;
    return blank;
}

void gfx_text(framebuffer_t *fb, int x, int y, const char *text,
              uint16_t color, int scale)
{
    for (const char *cursor = text; *cursor != '\0'; cursor++) {
        const uint8_t *rows = glyph_rows(*cursor);
        for (int row = 0; row < 7; row++) {
            for (int col = 0; col < 5; col++) {
                if ((rows[row] & (1u << (4 - col))) != 0)
                    gfx_rect(fb, x + col * scale, y + row * scale,
                             scale, scale, color);
            }
        }
        x += 6 * scale;
    }
}

static uint16_t read_le16(const uint8_t *p)
{
    return (uint16_t)(p[0] | ((uint16_t)p[1] << 8));
}

static uint32_t read_le32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8)
        | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

int bmp_load_rgb565(const char *path, uint16_t *pixels, int width, int height)
{
    FILE *file = fopen(path, "rb");
    if (file == NULL)
        return -1;

    uint8_t header[54];
    if (fread(header, 1, sizeof(header), file) != sizeof(header)
            || header[0] != 'B' || header[1] != 'M'
            || read_le16(&header[28]) != 24) {
        fclose(file);
        return -1;
    }

    int32_t bmp_width = (int32_t)read_le32(&header[18]);
    int32_t bmp_height = (int32_t)read_le32(&header[22]);
    int top_down = bmp_height < 0;
    if (bmp_height < 0)
        bmp_height = -bmp_height;
    if (bmp_width != width || bmp_height != height) {
        fclose(file);
        return -1;
    }

    uint32_t data_offset = read_le32(&header[10]);
    int row_bytes = (width * 3 + 3) & ~3;
    uint8_t *row = malloc((size_t)row_bytes);
    if (row == NULL) {
        fclose(file);
        return -1;
    }

    for (int y = 0; y < height; y++) {
        int source_y = top_down ? y : height - 1 - y;
        if (fseek(file, (long)data_offset + (long)source_y * row_bytes,
                  SEEK_SET) != 0
                || fread(row, 1, (size_t)row_bytes, file)
                    != (size_t)row_bytes) {
            free(row);
            fclose(file);
            return -1;
        }
        for (int x = 0; x < width; x++) {
            uint8_t b = row[x * 3];
            uint8_t g = row[x * 3 + 1];
            uint8_t r = row[x * 3 + 2];
            pixels[y * width + x] = rgb565(r, g, b);
        }
    }

    free(row);
    fclose(file);
    return 0;
}
