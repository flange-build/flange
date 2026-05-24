/**
 * gl_present.c — 见 gl_present.h
 */
#include "gl_present.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <poll.h>

#include <gbm.h>
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES2/gl2.h>

#define GL_FB_FORMAT GBM_FORMAT_XRGB8888

struct gl_ctx {
    int                 drm_fd;
    uint32_t            connector_id;
    uint32_t            crtc_id;
    drmModeModeInfo     mode;
    uint32_t            width;
    uint32_t            height;

    struct gbm_device  *gbm;
    struct gbm_surface *surface;

    EGLDisplay          dpy;
    EGLConfig           config;
    EGLContext          context;
    EGLSurface          egl_surface;

    struct gbm_bo      *prev_bo;
    int                 modeset_done;

    /* 纹理呈现管线 */
    GLuint              program;
    GLuint              texture;
    GLint               loc_pos;
    GLint               loc_tex;
    GLint               loc_sampler;
    uint32_t            tex_w;       /* LVGL 逻辑缓冲尺寸 */
    uint32_t            tex_h;
    int                 rotation;    /* 0/90/180/270 */
    char                renderer[96];/* GLES renderer 字符串 */
};

/* ------------------------------------------------------------------ */
/* 着色器：顶点透传；片元采样后 BGRA(内存序)→RGB swizzle，alpha 置 1     */
/* ------------------------------------------------------------------ */
static const char *VERT_SRC =
    "attribute vec2 a_pos;\n"
    "attribute vec2 a_tex;\n"
    "varying vec2 v_tex;\n"
    "void main() {\n"
    "    v_tex = a_tex;\n"
    "    gl_Position = vec4(a_pos, 0.0, 1.0);\n"
    "}\n";

static const char *FRAG_SRC =
    "precision mediump float;\n"
    "varying vec2 v_tex;\n"
    "uniform sampler2D u_tex;\n"
    "void main() {\n"
    "    vec4 c = texture2D(u_tex, v_tex);\n"
    "    gl_FragColor = vec4(c.b, c.g, c.r, 1.0);\n"
    "}\n";

/* 全屏 quad 顶点（TRIANGLE_STRIP 顺序：TL, BL, TR, BR） */
static const GLfloat QUAD_POS[8] = { -1.f, 1.f,  -1.f, -1.f,  1.f, 1.f,  1.f, -1.f };

/* 各旋转下，screen 角 [TL,BL,TR,BR] 对应的纹理坐标（顺时针旋转显示图像） */
static const GLfloat QUAD_TEX[4][8] = {
    /*   0 */ { 0,0,  0,1,  1,0,  1,1 },
    /*  90 */ { 0,1,  1,1,  0,0,  1,0 },
    /* 180 */ { 1,1,  1,0,  0,1,  0,0 },
    /* 270 */ { 1,0,  0,0,  1,1,  0,1 },
};

static GLuint compile_shader(GLenum type, const char *src)
{
    GLuint sh = glCreateShader(type);
    glShaderSource(sh, 1, &src, NULL);
    glCompileShader(sh);
    GLint ok = 0;
    glGetShaderiv(sh, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[512];
        glGetShaderInfoLog(sh, sizeof(log), NULL, log);
        fprintf(stderr, "[gl] 着色器编译失败: %s\n", log);
        glDeleteShader(sh);
        return 0;
    }
    return sh;
}

/* gbm_bo → drm fb id；首次为该 bo 创建并挂到 user data，destroy 时 RmFB */
static void bo_destroy_fb(struct gbm_bo *bo, void *data)
{
    uint32_t fb = (uint32_t)(uintptr_t)data;
    int fd = gbm_device_get_fd(gbm_bo_get_device(bo));
    if (fb)
        drmModeRmFB(fd, fb);
}

static uint32_t fb_for_bo(struct gl_ctx *gl, struct gbm_bo *bo)
{
    uint32_t fb = (uint32_t)(uintptr_t)gbm_bo_get_user_data(bo);
    if (fb)
        return fb;

    uint32_t handles[4] = {0}, strides[4] = {0}, offsets[4] = {0};
    handles[0] = gbm_bo_get_handle(bo).u32;
    strides[0] = gbm_bo_get_stride(bo);

    if (drmModeAddFB2(gl->drm_fd, gl->width, gl->height, GL_FB_FORMAT,
                      handles, strides, offsets, &fb, 0) != 0) {
        fprintf(stderr, "[gl] drmModeAddFB2 失败\n");
        return 0;
    }
    gbm_bo_set_user_data(bo, (void *)(uintptr_t)fb, bo_destroy_fb);
    return fb;
}

/* 选取 EGL_NATIVE_VISUAL_ID 匹配 GBM 帧缓冲格式的 EGLConfig */
static int choose_config(struct gl_ctx *gl)
{
    const EGLint attrs[] = {
        EGL_SURFACE_TYPE,    EGL_WINDOW_BIT,
        EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT,
        EGL_RED_SIZE,        8,
        EGL_GREEN_SIZE,      8,
        EGL_BLUE_SIZE,       8,
        EGL_ALPHA_SIZE,      0,
        EGL_NONE,
    };

    EGLint count = 0;
    if (!eglChooseConfig(gl->dpy, attrs, NULL, 0, &count) || count == 0)
        return -1;

    EGLConfig *configs = calloc(count, sizeof(EGLConfig));
    if (!configs)
        return -1;
    eglChooseConfig(gl->dpy, attrs, configs, count, &count);

    int ret = -1;
    for (EGLint i = 0; i < count; i++) {
        EGLint vid = 0;
        eglGetConfigAttrib(gl->dpy, configs[i], EGL_NATIVE_VISUAL_ID, &vid);
        if ((uint32_t)vid == GL_FB_FORMAT) {
            gl->config = configs[i];
            ret = 0;
            break;
        }
    }
    if (ret != 0 && count > 0) {
        gl->config = configs[0]; /* 退而求其次：取首个可用 config */
        ret = 0;
    }
    free(configs);
    return ret;
}

static EGLDisplay get_egl_display(struct gbm_device *gbm)
{
    /* 优先用 platform 扩展（明确 GBM 平台），失败回退 eglGetDisplay */
    const char *exts = eglQueryString(EGL_NO_DISPLAY, EGL_EXTENSIONS);
    if (exts && strstr(exts, "EGL_KHR_platform_gbm")) {
        PFNEGLGETPLATFORMDISPLAYEXTPROC get =
            (PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
        if (get)
            return get(EGL_PLATFORM_GBM_KHR, gbm, NULL);
    }
    return eglGetDisplay((EGLNativeDisplayType)gbm);
}

gl_ctx_t *gl_init(drm_dev_t *dev)
{
    struct gl_ctx *gl = calloc(1, sizeof(*gl));
    if (!gl)
        return NULL;

    gl->drm_fd       = dev->fd;
    gl->connector_id = dev->connector_id;
    gl->crtc_id      = dev->crtc_id;
    gl->mode         = dev->mode;
    gl->width        = dev->width;
    gl->height       = dev->height;

    gl->gbm = gbm_create_device(dev->fd);
    if (!gl->gbm) {
        fprintf(stderr, "[gl] gbm_create_device 失败\n");
        goto fail;
    }

    gl->surface = gbm_surface_create(gl->gbm, gl->width, gl->height, GL_FB_FORMAT,
                                     GBM_BO_USE_SCANOUT | GBM_BO_USE_RENDERING);
    if (!gl->surface) {
        fprintf(stderr, "[gl] gbm_surface_create 失败\n");
        goto fail;
    }

    gl->dpy = get_egl_display(gl->gbm);
    if (gl->dpy == EGL_NO_DISPLAY) {
        fprintf(stderr, "[gl] eglGetDisplay 失败\n");
        goto fail;
    }

    EGLint major = 0, minor = 0;
    if (!eglInitialize(gl->dpy, &major, &minor)) {
        fprintf(stderr, "[gl] eglInitialize 失败: 0x%x\n", eglGetError());
        goto fail;
    }
    fprintf(stderr, "[gl] EGL %d.%d vendor=%s\n", major, minor,
            eglQueryString(gl->dpy, EGL_VENDOR));

    if (!eglBindAPI(EGL_OPENGL_ES_API)) {
        fprintf(stderr, "[gl] eglBindAPI 失败\n");
        goto fail;
    }

    if (choose_config(gl) != 0) {
        fprintf(stderr, "[gl] 无匹配 EGLConfig\n");
        goto fail;
    }

    const EGLint ctx_attrs[] = { EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE };
    gl->context = eglCreateContext(gl->dpy, gl->config, EGL_NO_CONTEXT, ctx_attrs);
    if (gl->context == EGL_NO_CONTEXT) {
        fprintf(stderr, "[gl] eglCreateContext 失败: 0x%x\n", eglGetError());
        goto fail;
    }

    gl->egl_surface = eglCreateWindowSurface(gl->dpy, gl->config,
                                             (EGLNativeWindowType)gl->surface, NULL);
    if (gl->egl_surface == EGL_NO_SURFACE) {
        fprintf(stderr, "[gl] eglCreateWindowSurface 失败: 0x%x\n", eglGetError());
        goto fail;
    }

    if (!eglMakeCurrent(gl->dpy, gl->egl_surface, gl->egl_surface, gl->context)) {
        fprintf(stderr, "[gl] eglMakeCurrent 失败: 0x%x\n", eglGetError());
        goto fail;
    }

    const char *renderer = (const char *)glGetString(GL_RENDERER);
    fprintf(stderr, "[gl] GLES vendor=%s renderer=%s\n",
            (const char *)glGetString(GL_VENDOR), renderer);
    if (renderer)
        snprintf(gl->renderer, sizeof(gl->renderer), "%s", renderer);

    glViewport(0, 0, (GLsizei)gl->width, (GLsizei)gl->height);
    return gl;

fail:
    gl_deinit(gl);
    return NULL;
}

uint32_t gl_width(const gl_ctx_t *gl)  { return gl ? gl->width : 0; }
uint32_t gl_height(const gl_ctx_t *gl) { return gl ? gl->height : 0; }
const char *gl_renderer(const gl_ctx_t *gl) { return gl ? gl->renderer : ""; }

static void page_flip_handler(int fd, unsigned int seq, unsigned int s,
                              unsigned int us, void *data)
{
    (void)fd; (void)seq; (void)s; (void)us;
    *(int *)data = 0; /* 翻转完成 */
}

int gl_swap(gl_ctx_t *gl)
{
    if (!eglSwapBuffers(gl->dpy, gl->egl_surface)) {
        fprintf(stderr, "[gl] eglSwapBuffers 失败: 0x%x\n", eglGetError());
        return -1;
    }

    struct gbm_bo *bo = gbm_surface_lock_front_buffer(gl->surface);
    if (!bo) {
        fprintf(stderr, "[gl] lock_front_buffer 失败\n");
        return -1;
    }

    uint32_t fb = fb_for_bo(gl, bo);
    if (!fb) {
        gbm_surface_release_buffer(gl->surface, bo);
        return -1;
    }

    if (!gl->modeset_done) {
        if (drmModeSetCrtc(gl->drm_fd, gl->crtc_id, fb, 0, 0,
                           &gl->connector_id, 1, &gl->mode) != 0) {
            fprintf(stderr, "[gl] drmModeSetCrtc 失败\n");
            gbm_surface_release_buffer(gl->surface, bo);
            return -1;
        }
        gl->modeset_done = 1;
    } else {
        int waiting = 1;
        if (drmModePageFlip(gl->drm_fd, gl->crtc_id, fb,
                            DRM_MODE_PAGE_FLIP_EVENT, &waiting) == 0) {
            drmEventContext evctx = {
                .version = DRM_EVENT_CONTEXT_VERSION,
                .page_flip_handler = page_flip_handler,
            };
            struct pollfd pfd = { .fd = gl->drm_fd, .events = POLLIN };
            while (waiting) {
                if (poll(&pfd, 1, 100) <= 0)
                    break; /* 超时兜底，避免卡死 */
                drmHandleEvent(gl->drm_fd, &evctx);
            }
        }
    }

    if (gl->prev_bo)
        gbm_surface_release_buffer(gl->surface, gl->prev_bo);
    gl->prev_bo = bo;
    return 0;
}

int gl_present_setup(gl_ctx_t *gl, uint32_t tex_w, uint32_t tex_h)
{
    gl->tex_w = tex_w;
    gl->tex_h = tex_h;
    gl->rotation = 0;

    /* 编译链接着色器程序 */
    GLuint vs = compile_shader(GL_VERTEX_SHADER, VERT_SRC);
    GLuint fs = compile_shader(GL_FRAGMENT_SHADER, FRAG_SRC);
    if (!vs || !fs)
        return -1;
    gl->program = glCreateProgram();
    glAttachShader(gl->program, vs);
    glAttachShader(gl->program, fs);
    glLinkProgram(gl->program);
    glDeleteShader(vs);
    glDeleteShader(fs);
    GLint ok = 0;
    glGetProgramiv(gl->program, GL_LINK_STATUS, &ok);
    if (!ok) {
        char log[512];
        glGetProgramInfoLog(gl->program, sizeof(log), NULL, log);
        fprintf(stderr, "[gl] 程序链接失败: %s\n", log);
        return -1;
    }
    gl->loc_pos     = glGetAttribLocation(gl->program, "a_pos");
    gl->loc_tex     = glGetAttribLocation(gl->program, "a_tex");
    gl->loc_sampler = glGetUniformLocation(gl->program, "u_tex");

    /* 创建纹理（内容每帧由 LVGL 缓冲 subimage 更新） */
    glGenTextures(1, &gl->texture);
    glBindTexture(GL_TEXTURE_2D, gl->texture);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, (GLsizei)tex_w, (GLsizei)tex_h, 0,
                 GL_RGBA, GL_UNSIGNED_BYTE, NULL);

    glPixelStorei(GL_UNPACK_ALIGNMENT, 4);
    return 0;
}

void gl_present_set_rotation(gl_ctx_t *gl, int degrees)
{
    int r = ((degrees % 360) + 360) % 360;
    gl->rotation = (r / 90) * 90;  /* 量化到 0/90/180/270 */
}

void gl_present_resize(gl_ctx_t *gl, uint32_t tex_w, uint32_t tex_h)
{
    if (tex_w == gl->tex_w && tex_h == gl->tex_h)
        return;
    gl->tex_w = tex_w;
    gl->tex_h = tex_h;
    glBindTexture(GL_TEXTURE_2D, gl->texture);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, (GLsizei)tex_w, (GLsizei)tex_h, 0,
                 GL_RGBA, GL_UNSIGNED_BYTE, NULL);
}

int gl_present_frame(gl_ctx_t *gl, const void *pixels)
{
    glViewport(0, 0, (GLsizei)gl->width, (GLsizei)gl->height);
    glClearColor(0.961f, 0.953f, 0.933f, 1.0f);  /* 暖白兜底（quad 通常铺满） */
    glClear(GL_COLOR_BUFFER_BIT);

    glUseProgram(gl->program);

    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, gl->texture);
    glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, (GLsizei)gl->tex_w, (GLsizei)gl->tex_h,
                    GL_RGBA, GL_UNSIGNED_BYTE, pixels);
    glUniform1i(gl->loc_sampler, 0);

    const GLfloat *tex = QUAD_TEX[gl->rotation / 90];
    glEnableVertexAttribArray((GLuint)gl->loc_pos);
    glVertexAttribPointer((GLuint)gl->loc_pos, 2, GL_FLOAT, GL_FALSE, 0, QUAD_POS);
    glEnableVertexAttribArray((GLuint)gl->loc_tex);
    glVertexAttribPointer((GLuint)gl->loc_tex, 2, GL_FLOAT, GL_FALSE, 0, tex);

    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);

    glDisableVertexAttribArray((GLuint)gl->loc_pos);
    glDisableVertexAttribArray((GLuint)gl->loc_tex);

    return gl_swap(gl);
}

void gl_deinit(gl_ctx_t *gl)
{
    if (!gl)
        return;

    if (gl->texture)
        glDeleteTextures(1, &gl->texture);
    if (gl->program)
        glDeleteProgram(gl->program);

    if (gl->prev_bo)
        gbm_surface_release_buffer(gl->surface, gl->prev_bo);

    if (gl->dpy != EGL_NO_DISPLAY) {
        eglMakeCurrent(gl->dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
        if (gl->egl_surface != EGL_NO_SURFACE)
            eglDestroySurface(gl->dpy, gl->egl_surface);
        if (gl->context != EGL_NO_CONTEXT)
            eglDestroyContext(gl->dpy, gl->context);
        eglTerminate(gl->dpy);
    }
    if (gl->surface)
        gbm_surface_destroy(gl->surface);
    if (gl->gbm)
        gbm_device_destroy(gl->gbm);

    free(gl);
}
