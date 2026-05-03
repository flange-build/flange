/**
 * fb_triangle — 在 fb0 上用 GPU(EGL/GLES2) 渲染旋转三角形
 *
 * 流程：EGL/GBM 离屏 → GLES2 渲染 → glReadPixels → 写入 /dev/fb0
 * 适配 ST7789V SPI LCD (240x280, RGB565)
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/ioctl.h>
#include <linux/fb.h>

#include <EGL/egl.h>
#include <GLES2/gl2.h>

/* ---------- framebuffer ---------- */

static int fb_fd = -1;
static struct fb_fix_screeninfo fb_fix;
static struct fb_var_screeninfo fb_var;
static void *fb_mem = NULL;
static int fb_width, fb_height, fb_bpp, fb_stride_bytes;

static int fb_open(void)
{
    fb_fd = open("/dev/fb0", O_RDWR);
    if (fb_fd < 0) { perror("open /dev/fb0"); return -1; }

    if (ioctl(fb_fd, FBIOGET_FSCREENINFO, &fb_fix) < 0) {
        perror("FBIOGET_FSCREENINFO"); return -1;
    }
    if (ioctl(fb_fd, FBIOGET_VSCREENINFO, &fb_var) < 0) {
        perror("FBIOGET_VSCREENINFO"); return -1;
    }

    fb_width  = fb_var.xres;
    fb_height = fb_var.yres;
    fb_bpp    = fb_var.bits_per_pixel;
    fb_stride_bytes = fb_fix.line_length;

    printf("fb0: %dx%d, %dbpp, stride=%d\n",
           fb_width, fb_height, fb_bpp, fb_stride_bytes);

    fb_mem = mmap(NULL, fb_fix.smem_len,
                  PROT_READ | PROT_WRITE, MAP_SHARED, fb_fd, 0);
    if (fb_mem == MAP_FAILED) { perror("mmap fb0"); return -1; }

    return 0;
}

/* 将 RGBA8888 像素数据写入 fb0 (RGB565) */
static void fb_blit_rgb565(const unsigned char *rgba, int w, int h)
{
    unsigned short *dst = (unsigned short *)fb_mem;
    for (int y = 0; y < h && y < fb_height; y++) {
        for (int x = 0; x < w && x < fb_width; x++) {
            int src_idx = (y * w + x) * 4;
            unsigned char r = rgba[src_idx + 0];
            unsigned char g = rgba[src_idx + 1];
            unsigned char b = rgba[src_idx + 2];
            unsigned short rgb565 = ((r & 0xF8) << 8) |
                                    ((g & 0xFC) << 3) |
                                    (b >> 3);
            dst[y * (fb_stride_bytes / 2) + x] = rgb565;
        }
    }
}

static void fb_close(void)
{
    if (fb_mem && fb_mem != MAP_FAILED)
        munmap(fb_mem, fb_fix.smem_len);
    if (fb_fd >= 0) close(fb_fd);
}

/* ---------- EGL (surfaceless) ---------- */

static EGLDisplay egl_display = EGL_NO_DISPLAY;
static EGLContext egl_context = EGL_NO_CONTEXT;
static EGLSurface egl_surface = EGL_NO_SURFACE;

static int egl_init(int w, int h)
{
    egl_display = eglGetDisplay(EGL_DEFAULT_DISPLAY);
    if (egl_display == EGL_NO_DISPLAY) {
        fprintf(stderr, "eglGetDisplay failed\n"); return -1;
    }

    EGLint major, minor;
    if (!eglInitialize(egl_display, &major, &minor)) {
        fprintf(stderr, "eglInitialize failed\n"); return -1;
    }
    printf("EGL: %d.%d\n", major, minor);

    /* 选择 EGL 配置 */
    const EGLint attribs[] = {
        EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT,
        EGL_SURFACE_TYPE,    EGL_PBUFFER_BIT,
        EGL_RED_SIZE,   8,
        EGL_GREEN_SIZE, 8,
        EGL_BLUE_SIZE,  8,
        EGL_ALPHA_SIZE, 8,
        EGL_NONE
    };

    EGLConfig config;
    EGLint num_configs;
    if (!eglChooseConfig(egl_display, attribs, &config, 1, &num_configs)
        || num_configs < 1) {
        fprintf(stderr, "eglChooseConfig failed\n"); return -1;
    }

    /* 创建 PBuffer surface */
    const EGLint pbuf_attribs[] = {
        EGL_WIDTH,  w,
        EGL_HEIGHT, h,
        EGL_NONE
    };
    egl_surface = eglCreatePbufferSurface(egl_display, config, pbuf_attribs);
    if (egl_surface == EGL_NO_SURFACE) {
        fprintf(stderr, "eglCreatePbufferSurface failed: 0x%x\n", eglGetError());
        return -1;
    }

    /* 创建 GLES2 上下文 */
    const EGLint ctx_attribs[] = {
        EGL_CONTEXT_CLIENT_VERSION, 2,
        EGL_NONE
    };
    egl_context = eglCreateContext(egl_display, config, EGL_NO_CONTEXT, ctx_attribs);
    if (egl_context == EGL_NO_CONTEXT) {
        fprintf(stderr, "eglCreateContext failed: 0x%x\n", eglGetError());
        return -1;
    }

    if (!eglMakeCurrent(egl_display, egl_surface, egl_surface, egl_context)) {
        fprintf(stderr, "eglMakeCurrent failed: 0x%x\n", eglGetError());
        return -1;
    }

    printf("EGL context ready, renderer: %s\n", glGetString(GL_RENDERER));
    return 0;
}

static void egl_cleanup(void)
{
    if (egl_display != EGL_NO_DISPLAY) {
        eglMakeCurrent(egl_display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
        if (egl_surface != EGL_NO_SURFACE)
            eglDestroySurface(egl_display, egl_surface);
        if (egl_context != EGL_NO_CONTEXT)
            eglDestroyContext(egl_display, egl_context);
        eglTerminate(egl_display);
    }
}

/* ---------- GLES2 旋转三角形 ---------- */

static const char *vs_src =
    "attribute vec2 aPos;\n"
    "attribute vec3 aCol;\n"
    "varying vec3 vCol;\n"
    "uniform float uAngle;\n"
    "void main() {\n"
    "    float c = cos(uAngle);\n"
    "    float s = sin(uAngle);\n"
    "    mat2 rot = mat2(c, -s, s, c);\n"
    "    gl_Position = vec4(rot * aPos, 0.0, 1.0);\n"
    "    vCol = aCol;\n"
    "}\n";

static const char *fs_src =
    "precision mediump float;\n"
    "varying vec3 vCol;\n"
    "void main() {\n"
    "    gl_FragColor = vec4(vCol, 1.0);\n"
    "}\n";

static GLuint prog;
static GLint aPos_loc, aCol_loc, uAngle_loc;
static GLuint vbo;

static GLuint compile_shader(GLenum type, const char *src)
{
    GLuint s = glCreateShader(type);
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    GLint ok;
    glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[512];
        glGetShaderInfoLog(s, sizeof(log), NULL, log);
        fprintf(stderr, "shader compile error: %s\n", log);
        glDeleteShader(s);
        return 0;
    }
    return s;
}

static int gl_init(void)
{
    GLuint vs = compile_shader(GL_VERTEX_SHADER, vs_src);
    GLuint fs = compile_shader(GL_FRAGMENT_SHADER, fs_src);
    if (!vs || !fs) return -1;

    prog = glCreateProgram();
    glAttachShader(prog, vs);
    glAttachShader(prog, fs);
    glLinkProgram(prog);

    GLint ok;
    glGetProgramiv(prog, GL_LINK_STATUS, &ok);
    if (!ok) {
        char log[512];
        glGetProgramInfoLog(prog, sizeof(log), NULL, log);
        fprintf(stderr, "program link error: %s\n", log);
        return -1;
    }

    glDeleteShader(vs);
    glDeleteShader(fs);

    aPos_loc  = glGetAttribLocation(prog, "aPos");
    aCol_loc  = glGetAttribLocation(prog, "aCol");
    uAngle_loc = glGetUniformLocation(prog, "uAngle");

    /* 顶点数据: x, y, r, g, b */
    float verts[] = {
         0.0f,  0.7f,   1.0f, 0.0f, 0.0f,  /* 顶 - 红 */
        -0.6f, -0.5f,   0.0f, 1.0f, 0.0f,  /* 左下 - 绿 */
         0.6f, -0.5f,   0.0f, 0.0f, 1.0f,  /* 右下 - 蓝 */
    };

    glGenBuffers(1, &vbo);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);

    glUseProgram(prog);
    glEnableVertexAttribArray(aPos_loc);
    glVertexAttribPointer(aPos_loc, 2, GL_FLOAT, GL_FALSE,
                          5 * sizeof(float), (void *)0);
    glEnableVertexAttribArray(aCol_loc);
    glVertexAttribPointer(aCol_loc, 3, GL_FLOAT, GL_FALSE,
                          5 * sizeof(float), (void *)(2 * sizeof(float)));

    return 0;
}

static void gl_render(float angle)
{
    glViewport(0, 0, fb_width, fb_height);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    glUniform1f(uAngle_loc, angle);
    glDrawArrays(GL_TRIANGLES, 0, 3);
}

/* ---------- main ---------- */

int main(void)
{
    /* Mesa surfaceless 平台：无显示输出时仍可离屏渲染 */
    setenv("EGL_PLATFORM", "surfaceless", 1);

    if (fb_open() < 0) return 1;
    if (egl_init(fb_width, fb_height) < 0) { fb_close(); return 1; }
    if (gl_init() < 0) { egl_cleanup(); fb_close(); return 1; }

    int buf_sz = fb_width * fb_height * 4;
    unsigned char *pixels = malloc(buf_sz);
    unsigned char *flip_buf = malloc(fb_width * 4);
    if (!pixels || !flip_buf) { perror("malloc"); egl_cleanup(); fb_close(); return 1; }

    printf("渲染旋转三角形到 /dev/fb0 (%dx%d)...\n", fb_width, fb_height);
    printf("按 Ctrl+C 退出\n");

    float angle = 0.0f;
    for (;;) {
        gl_render(angle);
        eglSwapBuffers(egl_display, egl_surface);

        glReadPixels(0, 0, fb_width, fb_height,
                     GL_RGBA, GL_UNSIGNED_BYTE, pixels);

        /* OpenGL 原点在左下，fb0 原点在左上，需上下翻转 */
        int row_bytes = fb_width * 4;
        for (int y = 0; y < fb_height / 2; y++) {
            int top = y * row_bytes;
            int bot = (fb_height - 1 - y) * row_bytes;
            memcpy(flip_buf, pixels + top, row_bytes);
            memcpy(pixels + top, pixels + bot, row_bytes);
            memcpy(pixels + bot, flip_buf, row_bytes);
        }

        fb_blit_rgb565(pixels, fb_width, fb_height);

        angle += 0.03f;
        if (angle > 2.0f * M_PI) angle -= 2.0f * M_PI;

        usleep(16000);  /* ~60fps */
    }

    free(pixels);
    free(flip_buf);
    egl_cleanup();
    fb_close();
    return 0;
}
