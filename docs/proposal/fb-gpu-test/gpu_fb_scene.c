/**
 * GPU → fb0 动态场景渲染器
 *
 * 在 PowerVR BXM GPU 上离屏渲染 3D 动态场景，
 * 将像素读回后转换 RGBA→RGB565 写入 /dev/fb0。
 *
 * 场景内容：旋转 3D 圆环 + 逐顶点颜色光照 + 动态渐变背景
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <time.h>
#include <math.h>
#include <sys/ioctl.h>
#include <linux/fb.h>
#include <EGL/egl.h>
#include <GLES2/gl2.h>
#include <gbm.h>

#ifndef EGL_PLATFORM_GBM_KHR
#define EGL_PLATFORM_GBM_KHR 0x31D7
#endif

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* --- 着色器 --- */

static const char *bg_vert =
    "attribute vec2 a_pos;\n"
    "varying vec2 v_uv;\n"
    "void main() {\n"
    "    v_uv = a_pos * 0.5 + 0.5;\n"
    "    gl_Position = vec4(a_pos, 0.0, 1.0);\n"
    "}\n";

static const char *bg_frag =
    "precision mediump float;\n"
    "varying vec2 v_uv;\n"
    "uniform float u_time;\n"
    "void main() {\n"
    "    vec2 uv = v_uv;\n"
    "    float t = u_time * 0.3;\n"
    "    vec3 col = vec3(\n"
    "        0.5 + 0.3 * sin(uv.x * 4.0 + t),\n"
    "        0.3 + 0.2 * sin(uv.y * 3.0 + t * 1.3),\n"
    "        0.6 + 0.3 * sin(uv.x * 2.0 + uv.y * 4.0 + t * 0.7)\n"
    "    );\n"
    "    gl_FragColor = vec4(col, 1.0);\n"
    "}\n";

static const char *obj_vert =
    "attribute vec3 a_pos;\n"
    "attribute vec3 a_norm;\n"
    "attribute vec3 a_color;\n"
    "uniform mat4 u_mvp;\n"
    "uniform mat4 u_model;\n"
    "varying vec3 v_norm;\n"
    "varying vec3 v_color;\n"
    "void main() {\n"
    "    v_norm = mat3(u_model) * a_norm;\n"
    "    v_color = a_color;\n"
    "    gl_Position = u_mvp * vec4(a_pos, 1.0);\n"
    "}\n";

static const char *obj_frag =
    "precision mediump float;\n"
    "varying vec3 v_norm;\n"
    "varying vec3 v_color;\n"
    "uniform vec3 u_light_pos;\n"
    "void main() {\n"
    "    vec3 N = normalize(v_norm);\n"
    "    vec3 L = normalize(u_light_pos);\n"
    "    float diff = max(dot(N, L), 0.0) * 0.7 + 0.3;\n"
    "    gl_FragColor = vec4(v_color * diff, 1.0);\n"
    "}\n";

/* --- 矩阵工具 (列主序) --- */

typedef float Mat4[16];

static void mat4_identity(Mat4 m) {
    memset(m, 0, sizeof(Mat4));
    m[0] = m[5] = m[10] = m[15] = 1.0f;
}

static void mat4_multiply(Mat4 out, const Mat4 a, const Mat4 b) {
    for (int i = 0; i < 4; i++)
        for (int j = 0; j < 4; j++) {
            out[j * 4 + i] = 0;
            for (int k = 0; k < 4; k++)
                out[j * 4 + i] += a[k * 4 + i] * b[j * 4 + k];
        }
}

static void mat4_perspective(Mat4 m, float fov, float aspect, float near, float far) {
    float f = 1.0f / tanf(fov * 0.5f);
    memset(m, 0, sizeof(Mat4));
    m[0] = f / aspect;
    m[5] = f;
    m[10] = (far + near) / (near - far);
    m[11] = -1.0f;
    m[14] = 2.0f * far * near / (near - far);
}

static void mat4_lookat(Mat4 m, float eye[3], float center[3], float up[3]) {
    float f[3] = {center[0]-eye[0], center[1]-eye[1], center[2]-eye[2]};
    float fl = sqrtf(f[0]*f[0]+f[1]*f[1]+f[2]*f[2]);
    f[0]/=fl; f[1]/=fl; f[2]/=fl;
    float s[3] = {f[1]*up[2]-f[2]*up[1], f[2]*up[0]-f[0]*up[2], f[0]*up[1]-f[1]*up[0]};
    float sl = sqrtf(s[0]*s[0]+s[1]*s[1]+s[2]*s[2]);
    s[0]/=sl; s[1]/=sl; s[2]/=sl;
    float u[3] = {s[1]*f[2]-s[2]*f[1], s[2]*f[0]-s[0]*f[2], s[0]*f[1]-s[1]*f[0]};
    m[0]=s[0]; m[1]=u[0]; m[2]=-f[0]; m[3]=0;
    m[4]=s[1]; m[5]=u[1]; m[6]=-f[1]; m[7]=0;
    m[8]=s[2]; m[9]=u[2]; m[10]=-f[2]; m[11]=0;
    m[12]=-(s[0]*eye[0]+s[1]*eye[1]+s[2]*eye[2]);
    m[13]=-(u[0]*eye[0]+u[1]*eye[1]+u[2]*eye[2]);
    m[14]=f[0]*eye[0]+f[1]*eye[1]+f[2]*eye[2];
    m[15]=1;
}

static void mat4_rotate_y(Mat4 m, float angle) {
    mat4_identity(m);
    float c = cosf(angle), s = sinf(angle);
    m[0] = c; m[8] = s;
    m[2] = -s; m[10] = c;
}

static void mat4_rotate_x(Mat4 m, float angle) {
    mat4_identity(m);
    float c = cosf(angle), s = sinf(angle);
    m[5] = c; m[9] = -s;
    m[6] = s; m[10] = c;
}

static void mat4_translate(Mat4 m, float x, float y, float z) {
    mat4_identity(m);
    m[12] = x; m[13] = y; m[14] = z;
}

/* --- 几何体生成 --- */

static int gen_torus(float R, float r, int seg_major, int seg_minor,
                     float **out_v, float **out_n, float **out_c,
                     int **out_idx, int *out_idx_count) {
    int vcount = (seg_major + 1) * (seg_minor + 1);
    int tcount = seg_major * seg_minor * 6;
    *out_v = malloc(vcount * 3 * sizeof(float));
    *out_n = malloc(vcount * 3 * sizeof(float));
    *out_c = malloc(vcount * 3 * sizeof(float));
    *out_idx = malloc(tcount * sizeof(int));
    *out_idx_count = tcount;

    float palette[][3] = {
        {1.0f, 0.3f, 0.2f}, {0.2f, 0.8f, 0.3f}, {0.3f, 0.4f, 1.0f},
        {1.0f, 0.8f, 0.1f}, {0.8f, 0.2f, 0.9f}, {0.1f, 0.9f, 0.8f},
    };

    int vi = 0, ii = 0;
    for (int i = 0; i <= seg_major; i++) {
        float theta = (float)i / seg_major * 2.0f * (float)M_PI;
        float ct = cosf(theta), st = sinf(theta);
        for (int j = 0; j <= seg_minor; j++) {
            float phi = (float)j / seg_minor * 2.0f * (float)M_PI;
            float cp = cosf(phi), sp = sinf(phi);
            float x = (R + r * cp) * ct;
            float y = r * sp;
            float z = (R + r * cp) * st;
            float nx = cp * ct, ny = sp, nz = cp * st;
            (*out_v)[vi*3] = x; (*out_v)[vi*3+1] = y; (*out_v)[vi*3+2] = z;
            (*out_n)[vi*3] = nx; (*out_n)[vi*3+1] = ny; (*out_n)[vi*3+2] = nz;
            int ci = i % 6;
            (*out_c)[vi*3] = palette[ci][0];
            (*out_c)[vi*3+1] = palette[ci][1];
            (*out_c)[vi*3+2] = palette[ci][2];
            vi++;
        }
    }
    for (int i = 0; i < seg_major; i++) {
        for (int j = 0; j < seg_minor; j++) {
            int a = i * (seg_minor + 1) + j;
            int b = a + seg_minor + 1;
            (*out_idx)[ii++] = a; (*out_idx)[ii++] = b; (*out_idx)[ii++] = a + 1;
            (*out_idx)[ii++] = a + 1; (*out_idx)[ii++] = b; (*out_idx)[ii++] = b + 1;
        }
    }
    return vcount;
}

/* --- GPU 初始化 --- */

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

static GLuint link_program(const char *vert_src, const char *frag_src) {
    GLuint vs = compile_shader(GL_VERTEX_SHADER, vert_src);
    GLuint fs = compile_shader(GL_FRAGMENT_SHADER, frag_src);
    if (!vs || !fs) return 0;
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
        return 0;
    }
    glDeleteShader(vs);
    glDeleteShader(fs);
    return prog;
}

static int init_egl(EGLDisplay *out_d, EGLContext *out_c, EGLSurface *out_s,
                    int width, int height) {
    int fd = open("/dev/dri/renderD128", O_RDWR);
    if (fd < 0) { fprintf(stderr, "renderD128 打开失败\n"); return -1; }

    struct gbm_device *gbm = gbm_create_device(fd);
    if (!gbm) { fprintf(stderr, "gbm_create_device 失败\n"); close(fd); return -1; }

    EGLDisplay display = eglGetPlatformDisplay(EGL_PLATFORM_GBM_KHR, gbm, NULL);
    if (display == EGL_NO_DISPLAY || !eglInitialize(display, NULL, NULL))
        return -1;

    printf("EGL Vendor: %s\n", eglQueryString(display, EGL_VENDOR));
    eglBindAPI(EGL_OPENGL_ES_API);

    static const EGLint config_attrs[] = {
        EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT,
        EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8,
        EGL_NONE,
    };
    EGLConfig config; EGLint num_config;
    if (!eglChooseConfig(display, config_attrs, &config, 1, &num_config) || !num_config)
        return -1;

    struct gbm_surface *gbm_surf = gbm_surface_create(
        gbm, width, height, GBM_FORMAT_ARGB8888, GBM_BO_USE_RENDERING);
    if (!gbm_surf) return -1;

    EGLSurface surface = eglCreatePlatformWindowSurface(display, config, gbm_surf, NULL);
    if (surface == EGL_NO_SURFACE) return -1;

    static const EGLint ctx_attrs[] = { EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE };
    EGLContext context = eglCreateContext(display, config, EGL_NO_CONTEXT, ctx_attrs);
    if (context == EGL_NO_CONTEXT) return -1;

    if (!eglMakeCurrent(display, surface, surface, context)) return -1;

    *out_d = display; *out_c = context; *out_s = surface;
    return 0;
}

/* --- fb0 写入 --- */

static int fb_fd = -1;
static int fb_width = 0, fb_height = 0;
static unsigned char *fb_rgb565 = NULL;

static int fb_init(void) {
    fb_fd = open("/dev/fb0", O_RDWR);
    if (fb_fd < 0) { perror("open /dev/fb0"); return -1; }

    struct fb_var_screeninfo vinfo;
    if (ioctl(fb_fd, FBIOGET_VSCREENINFO, &vinfo) < 0) { perror("ioctl"); return -1; }
    fb_width = vinfo.xres;
    fb_height = vinfo.yres;

    fb_rgb565 = malloc(fb_width * fb_height * 2);
    if (!fb_rgb565) return -1;

    printf("fb0: %dx%d, bpp=%d\n", fb_width, fb_height, vinfo.bits_per_pixel);
    return 0;
}

static void fb_blit(const unsigned char *rgba, int w, int h) {
    int bw = w < fb_width ? w : fb_width;
    int bh = h < fb_height ? h : fb_height;
    for (int y = 0; y < bh; y++) {
        const unsigned char *row = rgba + y * w * 4;
        unsigned short *out = (unsigned short *)(fb_rgb565 + y * fb_width * 2);
        for (int x = 0; x < bw; x++) {
            unsigned char r = row[x*4], g = row[x*4+1], b = row[x*4+2];
            out[x] = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3);
        }
    }
    lseek(fb_fd, 0, SEEK_SET);
    write(fb_fd, fb_rgb565, fb_width * fb_height * 2);
}

/* --- main --- */

int main(void) {
    if (fb_init() < 0) return 1;
    int W = fb_width, H = fb_height;

    EGLDisplay display; EGLContext context; EGLSurface surface;
    if (init_egl(&display, &context, &surface, W, H) < 0) return 1;

    printf("GL_RENDERER: %s\n", glGetString(GL_RENDERER));

    GLuint bg_prog = link_program(bg_vert, bg_frag);
    GLuint obj_prog = link_program(obj_vert, obj_frag);
    if (!bg_prog || !obj_prog) return 1;

    /* 背景 VBO */
    static const float quad[] = { -1,-1, 1,-1, -1,1, -1,1, 1,-1, 1,1 };
    GLuint bg_vbo;
    glGenBuffers(1, &bg_vbo);
    glBindBuffer(GL_ARRAY_BUFFER, bg_vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
    GLint bg_a_pos = glGetAttribLocation(bg_prog, "a_pos");
    GLint bg_u_time = glGetUniformLocation(bg_prog, "u_time");

    /* 圆环几何体 */
    float *torus_v, *torus_n, *torus_c;
    int *torus_idx; int torus_idx_count;
    int torus_vcount = gen_torus(0.7f, 0.3f, 48, 24,
                                  &torus_v, &torus_n, &torus_c,
                                  &torus_idx, &torus_idx_count);

    GLuint vbo_pos, vbo_norm, vbo_color, ibo;
    glGenBuffers(1, &vbo_pos);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_pos);
    glBufferData(GL_ARRAY_BUFFER, torus_vcount*3*sizeof(float), torus_v, GL_STATIC_DRAW);
    glGenBuffers(1, &vbo_norm);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_norm);
    glBufferData(GL_ARRAY_BUFFER, torus_vcount*3*sizeof(float), torus_n, GL_STATIC_DRAW);
    glGenBuffers(1, &vbo_color);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_color);
    glBufferData(GL_ARRAY_BUFFER, torus_vcount*3*sizeof(float), torus_c, GL_STATIC_DRAW);
    glGenBuffers(1, &ibo);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ibo);
    glBufferData(GL_ELEMENT_ARRAY_BUFFER, torus_idx_count*sizeof(int),
                 torus_idx, GL_STATIC_DRAW);

    GLint obj_a_pos = glGetAttribLocation(obj_prog, "a_pos");
    GLint obj_a_norm = glGetAttribLocation(obj_prog, "a_norm");
    GLint obj_a_color = glGetAttribLocation(obj_prog, "a_color");
    GLint obj_u_mvp = glGetUniformLocation(obj_prog, "u_mvp");
    GLint obj_u_model = glGetUniformLocation(obj_prog, "u_model");
    GLint obj_u_light = glGetUniformLocation(obj_prog, "u_light_pos");

    free(torus_v); free(torus_n); free(torus_c); free(torus_idx);

    unsigned char *pixels = malloc(W * H * 4);
    glViewport(0, 0, W, H);
    glEnable(GL_DEPTH_TEST);

    float eye[3] = {0, 1.5f, 3.0f};
    float center[3] = {0, 0, 0};
    float up[3] = {0, 1, 0};
    Mat4 proj, view, vp;
    mat4_perspective(proj, 1.2f, (float)W / (float)H, 0.1f, 100.0f);
    mat4_lookat(view, eye, center, up);
    mat4_multiply(vp, proj, view);

    printf("渲染循环开始 (%dx%d)...\n", W, H);
    struct timespec t0;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    int frame = 0;

    while (1) {
        struct timespec now;
        clock_gettime(CLOCK_MONOTONIC, &now);
        float time_s = (now.tv_sec - t0.tv_sec) +
                       (now.tv_nsec - t0.tv_nsec) / 1e9f;

        /* 绘制背景 */
        glDisable(GL_DEPTH_TEST);
        glUseProgram(bg_prog);
        glUniform1f(bg_u_time, time_s);
        glBindBuffer(GL_ARRAY_BUFFER, bg_vbo);
        glEnableVertexAttribArray(bg_a_pos);
        glVertexAttribPointer(bg_a_pos, 2, GL_FLOAT, GL_FALSE, 0, 0);
        glDrawArrays(GL_TRIANGLES, 0, 6);
        glDisableVertexAttribArray(bg_a_pos);

        /* 绘制圆环 */
        glEnable(GL_DEPTH_TEST);
        glClearDepthf(1.0f);
        glClear(GL_DEPTH_BUFFER_BIT);
        glUseProgram(obj_prog);

        Mat4 ry, rx, t, model, mvp;
        mat4_rotate_y(ry, time_s * 0.8f);
        mat4_rotate_x(rx, time_s * 0.5f);
        mat4_multiply(t, ry, rx);
        mat4_translate(model, 0, 0, 0);
        mat4_multiply(model, model, t);
        mat4_multiply(mvp, vp, model);

        glUniformMatrix4fv(obj_u_mvp, 1, GL_FALSE, mvp);
        glUniformMatrix4fv(obj_u_model, 1, GL_FALSE, model);

        float light[3] = {3.0f * sinf(time_s * 1.2f),
                          3.0f,
                          3.0f * cosf(time_s * 1.2f)};
        glUniform3fv(obj_u_light, 1, light);

        glBindBuffer(GL_ARRAY_BUFFER, vbo_pos);
        glEnableVertexAttribArray(obj_a_pos);
        glVertexAttribPointer(obj_a_pos, 3, GL_FLOAT, GL_FALSE, 0, 0);
        glBindBuffer(GL_ARRAY_BUFFER, vbo_norm);
        glEnableVertexAttribArray(obj_a_norm);
        glVertexAttribPointer(obj_a_norm, 3, GL_FLOAT, GL_FALSE, 0, 0);
        glBindBuffer(GL_ARRAY_BUFFER, vbo_color);
        glEnableVertexAttribArray(obj_a_color);
        glVertexAttribPointer(obj_a_color, 3, GL_FLOAT, GL_FALSE, 0, 0);
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ibo);
        glDrawElements(GL_TRIANGLES, torus_idx_count, GL_UNSIGNED_INT, 0);
        glDisableVertexAttribArray(obj_a_pos);
        glDisableVertexAttribArray(obj_a_norm);
        glDisableVertexAttribArray(obj_a_color);

        /* 读回并写入 fb0 */
        glFinish();
        glReadPixels(0, 0, W, H, GL_RGBA, GL_UNSIGNED_BYTE, pixels);

        /* GL 原点左下，fb0 原点左上，上下翻转 */
        int stride = W * 4;
        unsigned char *flip_buf = malloc(H * stride);
        for (int y = 0; y < H; y++)
            memcpy(flip_buf + y * stride, pixels + (H - 1 - y) * stride, stride);
        fb_blit(flip_buf, W, H);
        free(flip_buf);

        frame++;
        usleep(30000);
        if (frame % 30 == 0) {
            float elapsed = time_s > 0 ? time_s : 0.001f;
            printf("  %d 帧, %.1f fps\n", frame, frame / elapsed);
        }
    }

    free(pixels);
    return 0;
}
