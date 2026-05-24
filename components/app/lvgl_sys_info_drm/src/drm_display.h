/**
 * drm_display.h — DRM 显示设备与 connector 自动选择
 *
 * 遍历 /dev/dri/card*，挑选第一个存在已连接 connector（DRM_MODE_CONNECTED）
 * 且能绑定可用 CRTC 的节点（绝不写死 card 编号）。分辨率取该 connector 的
 * preferred mode。
 */
#ifndef DRM_DISPLAY_H
#define DRM_DISPLAY_H

#include <stdint.h>
#include <xf86drm.h>
#include <xf86drmMode.h>

typedef struct {
    int                 fd;             /* DRM 设备 fd */
    char                path[64];       /* /dev/dri/cardN */
    uint32_t            connector_id;
    uint32_t            crtc_id;
    uint32_t            width;          /* preferred mode 宽 */
    uint32_t            height;         /* preferred mode 高 */
    drmModeModeInfo     mode;           /* 选定显示模式 */
    drmModeCrtc        *saved_crtc;     /* 进入前的 CRTC 状态，退出时复原 */
    int                 has_master;     /* 是否已取得 DRM master */
} drm_dev_t;

/**
 * 枚举并打开首个有已连接屏幕的 DRM 设备，取得 DRM master。
 * 成功返回 0 并填充 dev；无可用设备返回 -1（已打印诊断）。
 */
int drm_open_first_connected(drm_dev_t *dev);

/**
 * 释放 DRM master、复原 CRTC、关闭 fd。
 */
void drm_close(drm_dev_t *dev);

#endif /* DRM_DISPLAY_H */
