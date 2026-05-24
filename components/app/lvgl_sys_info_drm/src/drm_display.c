/**
 * drm_display.c — 见 drm_display.h
 */
#include "drm_display.h"

#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

/* 选取 connector 的显示模式：优先 PREFERRED，否则取第一个 */
static const drmModeModeInfo *pick_mode(const drmModeConnector *conn)
{
    for (int i = 0; i < conn->count_modes; i++) {
        if (conn->modes[i].type & DRM_MODE_TYPE_PREFERRED)
            return &conn->modes[i];
    }
    return conn->count_modes > 0 ? &conn->modes[0] : NULL;
}

/* 为已连接 connector 找一个可绑定的 CRTC id；失败返回 0 */
static uint32_t find_crtc(int fd, drmModeRes *res, drmModeConnector *conn)
{
    /* 先沿用 connector 当前的 encoder（若已绑定 CRTC） */
    if (conn->encoder_id) {
        drmModeEncoder *enc = drmModeGetEncoder(fd, conn->encoder_id);
        if (enc) {
            uint32_t crtc = enc->crtc_id;
            drmModeFreeEncoder(enc);
            if (crtc)
                return crtc;
        }
    }
    /* 否则遍历 connector 支持的所有 encoder × CRTC 组合 */
    for (int i = 0; i < conn->count_encoders; i++) {
        drmModeEncoder *enc = drmModeGetEncoder(fd, conn->encoders[i]);
        if (!enc)
            continue;
        for (int c = 0; c < res->count_crtcs; c++) {
            if (enc->possible_crtcs & (1u << c)) {
                uint32_t crtc = res->crtcs[c];
                drmModeFreeEncoder(enc);
                return crtc;
            }
        }
        drmModeFreeEncoder(enc);
    }
    return 0;
}

/* 在单个 DRM fd 上尝试找到 connected connector + CRTC，成功填充 dev 返回 0 */
static int probe_device(int fd, const char *path, drm_dev_t *dev)
{
    drmModeRes *res = drmModeGetResources(fd);
    if (!res)
        return -1; /* 无显示能力（如 render-only 节点） */

    int ret = -1;
    for (int i = 0; i < res->count_connectors; i++) {
        drmModeConnector *conn = drmModeGetConnector(fd, res->connectors[i]);
        if (!conn)
            continue;

        if (conn->connection == DRM_MODE_CONNECTED && conn->count_modes > 0) {
            const drmModeModeInfo *mode = pick_mode(conn);
            uint32_t crtc = mode ? find_crtc(fd, res, conn) : 0;
            if (mode && crtc) {
                dev->connector_id = conn->connector_id;
                dev->crtc_id      = crtc;
                dev->mode         = *mode;
                dev->width        = mode->hdisplay;
                dev->height       = mode->vdisplay;
                snprintf(dev->path, sizeof(dev->path), "%s", path);
                ret = 0;
            }
        }
        drmModeFreeConnector(conn);
        if (ret == 0)
            break;
    }

    drmModeFreeResources(res);
    return ret;
}

int drm_open_first_connected(drm_dev_t *dev)
{
    memset(dev, 0, sizeof(*dev));
    dev->fd = -1;

    char path[64];
    for (int i = 0; i < 16; i++) {
        snprintf(path, sizeof(path), "/dev/dri/card%d", i);
        int fd = open(path, O_RDWR | O_CLOEXEC);
        if (fd < 0)
            continue;

        if (probe_device(fd, path, dev) == 0) {
            dev->fd = fd;
            /* 取得 DRM master（独占上屏所需） */
            if (drmSetMaster(fd) == 0) {
                dev->has_master = 1;
            } else {
                fprintf(stderr, "[drm] 警告：%s 取 DRM master 失败（是否已被 compositor 占用？）\n", path);
            }
            /* 保存进入前 CRTC，退出时复原 */
            dev->saved_crtc = drmModeGetCrtc(fd, dev->crtc_id);
            fprintf(stderr, "[drm] 选定显示设备 %s connector=%u crtc=%u %ux%u@%u\n",
                    dev->path, dev->connector_id, dev->crtc_id,
                    dev->width, dev->height, dev->mode.vrefresh);
            return 0;
        }
        close(fd);
    }

    fprintf(stderr, "[drm] 错误：/dev/dri/card0..15 中无任何已连接显示设备\n");
    return -1;
}

void drm_close(drm_dev_t *dev)
{
    if (!dev || dev->fd < 0)
        return;

    if (dev->saved_crtc) {
        drmModeSetCrtc(dev->fd, dev->saved_crtc->crtc_id, dev->saved_crtc->buffer_id,
                       dev->saved_crtc->x, dev->saved_crtc->y,
                       &dev->connector_id, 1, &dev->saved_crtc->mode);
        drmModeFreeCrtc(dev->saved_crtc);
        dev->saved_crtc = NULL;
    }
    if (dev->has_master)
        drmDropMaster(dev->fd);

    close(dev->fd);
    dev->fd = -1;
}
