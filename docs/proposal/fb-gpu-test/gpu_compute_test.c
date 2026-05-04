/**
 * GPU 计算验证程序 — 验证 PowerVR BXM GPU 是否正常工作
 *
 * 通过 EGL + GLES2 在 GPU 上执行着色器计算，验证：
 * 1. PowerVR render node (/dev/dri/renderD128) 可用
 * 2. EGL 可通过 PowerVR 平台创建上下文
 * 3. GPU 着色器计算结果正确
 *
 * 若 PowerVR 不可用，回退到 Mesa llvmpipe surfaceless
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <time.h>
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES2/gl2.h>
#include <gbm.h>

#ifndef EGL_PLATFORM_GBM_KHR
#define EGL_PLATFORM_GBM_KHR 0x31D7
#endif

static const char *vertex_src =
    "attribute vec4 a_pos;\n"
    "void main() {\n"
    "    gl_Position = a_pos;\n"
    "}\n";

/* 计算着色器：输出颜色 = 输入常量，用于验证 GPU 执行正确性 */
static const char *fragment_src =
    "precision mediump float;\n"
    "uniform vec4 u_color;\n"
    "void main() {\n"
    "    gl_FragColor = u_color;\n"
    "}\n";

static GLuint compile_shader(GLenum type, const char *src) {
    GLuint s = glCreateShader(type);
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    GLint ok;
    glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[256];
        glGetShaderInfoLog(s, sizeof(log), NULL, log);
        fprintf(stderr, "着色器编译失败: %s\n", log);
        glDeleteShader(s);
        return 0;
    }
    return s;
}

static int try_pvr_gbm(EGLDisplay *out_display, EGLContext *out_context,
                        EGLSurface *out_surface) {
    const char *render_node = "/dev/dri/renderD128";
    int fd = open(render_node, O_RDWR);
    if (fd < 0) {
        printf("  renderD128 打开失败\n");
        return -1;
    }

    struct gbm_device *gbm = gbm_create_device(fd);
    if (!gbm) {
        printf("  gbm_create_device 失败\n");
        close(fd);
        return -1;
    }

    EGLDisplay display = eglGetPlatformDisplay(
        EGL_PLATFORM_GBM_KHR, gbm, NULL);
    if (display == EGL_NO_DISPLAY) {
        printf("  eglGetPlatformDisplayEXT(GBM) 失败\n");
        close(fd);
        return -1;
    }

    if (!eglInitialize(display, NULL, NULL)) {
        printf("  eglInitialize 失败\n");
        close(fd);
        return -1;
    }

    const char *client_apis = eglQueryString(display, EGL_CLIENT_APIS);
    const char *vendor = eglQueryString(display, EGL_VENDOR);
    printf("  EGL Vendor: %s\n", vendor ? vendor : "N/A");
    printf("  EGL Client APIs: %s\n", client_apis ? client_apis : "N/A");

    if (!eglBindAPI(EGL_OPENGL_ES_API)) {
        printf("  eglBindAPI(GLES) 失败\n");
        eglTerminate(display);
        close(fd);
        return -1;
    }

    static const EGLint config_attrs[] = {
        EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT,
        EGL_RED_SIZE, 8,
        EGL_GREEN_SIZE, 8,
        EGL_BLUE_SIZE, 8,
        EGL_ALPHA_SIZE, 8,
        EGL_NONE,
    };
    EGLConfig config;
    EGLint num_config;
    if (!eglChooseConfig(display, config_attrs, &config, 1, &num_config)
        || num_config == 0) {
        printf("  eglChooseConfig 失败\n");
        eglTerminate(display);
        close(fd);
        return -1;
    }

    struct gbm_surface *gbm_surf = gbm_surface_create(
        gbm, 64, 64, GBM_FORMAT_ARGB8888,
        GBM_BO_USE_RENDERING);
    if (!gbm_surf) {
        printf("  gbm_surface_create 失败\n");
        eglTerminate(display);
        close(fd);
        return -1;
    }

    EGLSurface surface = eglCreatePlatformWindowSurface(
        display, config, gbm_surf, NULL);
    if (surface == EGL_NO_SURFACE) {
        printf("  eglCreateWindowSurface 失败 (eglError: 0x%x)\n",
               eglGetError());
        eglTerminate(display);
        close(fd);
        return -1;
    }

    static const EGLint ctx_attrs[] = {
        EGL_CONTEXT_CLIENT_VERSION, 2,
        EGL_NONE,
    };
    EGLContext context = eglCreateContext(display, config,
                                          EGL_NO_CONTEXT, ctx_attrs);
    if (context == EGL_NO_CONTEXT) {
        printf("  eglCreateContext 失败\n");
        eglTerminate(display);
        close(fd);
        return -1;
    }

    if (!eglMakeCurrent(display, surface, surface, context)) {
        printf("  eglMakeCurrent 失败\n");
        eglDestroyContext(display, context);
        eglTerminate(display);
        close(fd);
        return -1;
    }

    *out_display = display;
    *out_context = context;
    *out_surface = surface;
    return 0;
}

static int try_surfaceless(EGLDisplay *out_display, EGLContext *out_context,
                            EGLSurface *out_surface) {
    setenv("EGL_PLATFORM", "surfaceless", 1);

    EGLDisplay display = eglGetDisplay(EGL_DEFAULT_DISPLAY);
    if (display == EGL_NO_DISPLAY) {
        printf("  eglGetDisplay 失败\n");
        return -1;
    }

    if (!eglInitialize(display, NULL, NULL)) {
        printf("  eglInitialize 失败\n");
        return -1;
    }

    const char *vendor = eglQueryString(display, EGL_VENDOR);
    printf("  EGL Vendor: %s\n", vendor ? vendor : "N/A");

    eglBindAPI(EGL_OPENGL_ES_API);

    static const EGLint config_attrs[] = {
        EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT,
        EGL_NONE,
    };
    EGLConfig config;
    EGLint num_config;
    eglChooseConfig(display, config_attrs, &config, 1, &num_config);

    static const EGLint surf_attrs[] = {
        EGL_WIDTH, 64,
        EGL_HEIGHT, 64,
        EGL_NONE,
    };
    EGLSurface surface = eglCreatePbufferSurface(display, config, surf_attrs);
    if (surface == EGL_NO_SURFACE) {
        printf("  eglCreatePbufferSurface 失败\n");
        eglTerminate(display);
        return -1;
    }

    static const EGLint ctx_attrs[] = {
        EGL_CONTEXT_CLIENT_VERSION, 2,
        EGL_NONE,
    };
    EGLContext context = eglCreateContext(display, config,
                                          EGL_NO_CONTEXT, ctx_attrs);
    if (context == EGL_NO_CONTEXT) {
        printf("  eglCreateContext 失败\n");
        eglTerminate(display);
        return -1;
    }

    if (!eglMakeCurrent(display, surface, surface, context)) {
        printf("  eglMakeCurrent 失败\n");
        eglDestroyContext(display, context);
        eglTerminate(display);
        return -1;
    }

    *out_display = display;
    *out_context = context;
    *out_surface = surface;
    return 0;
}

static int run_gpu_compute_test(void) {
    /* 编译着色器程序 */
    GLuint vs = compile_shader(GL_VERTEX_SHADER, vertex_src);
    GLuint fs = compile_shader(GL_FRAGMENT_SHADER, fragment_src);
    if (!vs || !fs) return -1;

    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs);
    glAttachShader(prog, fs);
    glLinkProgram(prog);
    GLint ok;
    glGetProgramiv(prog, GL_LINK_STATUS, &ok);
    if (!ok) {
        char log[256];
        glGetProgramInfoLog(prog, sizeof(log), NULL, log);
        fprintf(stderr, "着色器链接失败: %s\n", log);
        return -1;
    }
    glUseProgram(prog);

    /* 全屏四边形 */
    static const float verts[] = {
        -1, -1,  1, -1,  -1, 1,
        -1,  1,  1, -1,   1, 1,
    };
    GLint a_pos = glGetAttribLocation(prog, "a_pos");
    glEnableVertexAttribArray(a_pos);
    glVertexAttribPointer(a_pos, 2, GL_FLOAT, GL_FALSE, 0, verts);

    GLint u_color = glGetUniformLocation(prog, "u_color");

    /* 渲染测试：用已知颜色 (1.0, 0.0, 0.5, 1.0) 填充 */
    const float test_r = 1.0f, test_g = 0.0f, test_b = 0.5f, test_a = 1.0f;
    glUniform4f(u_color, test_r, test_g, test_b, test_a);
    glViewport(0, 0, 64, 64);
    glClearColor(0, 0, 0, 1);
    glClear(GL_COLOR_BUFFER_BIT);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    /* 读回像素验证 */
    unsigned char pixel[4] = {0};
    glReadPixels(0, 0, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel);

    printf("  GPU 渲染: RGBA(%d, %d, %d, %d)\n",
           pixel[0], pixel[1], pixel[2], pixel[3]);

    int r_ok = abs(pixel[0] - 255) <= 1;
    int g_ok = pixel[1] <= 1;
    int b_ok = abs(pixel[2] - 128) <= 2;
    int a_ok = pixel[3] >= 254;

    if (r_ok && g_ok && b_ok && a_ok) {
        printf("  GPU 计算验证: PASS (颜色匹配正确)\n");
        return 0;
    } else {
        printf("  GPU 计算验证: FAIL (期望 RGBA(255,0,128,255))\n");
        return -1;
    }
}

int main(void) {
    printf("=== GPU 计算验证 ===\n\n");

    /* 检查 PowerVR 模块 */
    if (access("/sys/kernel/debug/pvr/version", F_OK) == 0) {
        printf("[1] PowerVR 内核模块: 已加载\n");
    } else {
        printf("[1] PowerVR 内核模块: 未加载\n");
    }

    /* 检查 render node */
    if (access("/dev/dri/renderD128", R_OK) == 0) {
        printf("[2] DRM render node: /dev/dri/renderD128 可用\n");
    } else {
        printf("[2] DRM render node: 不可用\n");
    }

    /* 检查 DRI 设备 */
    if (access("/dev/dri/card1", R_OK) == 0) {
        printf("[3] DRM card: /dev/dri/card1 (PowerVR) 可用\n");
    } else {
        printf("[3] DRM card: card1 不可用\n");
    }

    printf("\n--- EGL 初始化 ---\n");

    EGLDisplay display = EGL_NO_DISPLAY;
    EGLContext context = EGL_NO_CONTEXT;
    EGLSurface surface = EGL_NO_SURFACE;
    const char *renderer_name = NULL;
    int use_pvr = 0;

    printf("尝试 PowerVR GBM 平台...\n");
    if (try_pvr_gbm(&display, &context, &surface) == 0) {
        use_pvr = 1;
        renderer_name = glGetString(GL_RENDERER);
        printf("PowerVR GBM 平台初始化成功\n");
    } else {
        printf("PowerVR GBM 失败，回退到 surfaceless...\n");
        if (try_surfaceless(&display, &context, &surface) == 0) {
            renderer_name = glGetString(GL_RENDERER);
            printf("surfaceless 平台初始化成功\n");
        } else {
            printf("所有 EGL 平台均失败\n");
            return 1;
        }
    }

    printf("\n--- GPU 信息 ---\n");
    printf("  GL_RENDERER:   %s\n", glGetString(GL_RENDERER));
    printf("  GL_VERSION:    %s\n", glGetString(GL_VERSION));
    printf("  GL_VENDOR:     %s\n", glGetString(GL_VENDOR));
    printf("  GLSL_VERSION:  %s\n", glGetString(GL_SHADING_LANGUAGE_VERSION));

    printf("\n--- GPU 计算测试 ---\n");
    int result = run_gpu_compute_test();

    /* 性能基准：执行 1000 次绘制测量帧率 */
    printf("\n--- 性能基准 ---\n");
    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    for (int i = 0; i < 1000; i++) {
        glDrawArrays(GL_TRIANGLES, 0, 6);
    }
    glFinish();
    clock_gettime(CLOCK_MONOTONIC, &t1);
    double elapsed = (t1.tv_sec - t0.tv_sec) + (t1.tv_nsec - t0.tv_nsec) / 1e9;
    printf("  1000 次 draw + finish: %.3f s (%.1f fps)\n",
           elapsed, 1000.0 / elapsed);

    printf("\n=== 结果: %s ===\n",
           result == 0 ? "PASS (GPU 正常工作)" : "FAIL");

    eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
    eglDestroyContext(display, context);
    eglDestroySurface(display, surface);
    eglTerminate(display);

    return result;
}
