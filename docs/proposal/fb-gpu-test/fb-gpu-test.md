# fb0 GPU 渲染测试 — 旋转三角形

## 概述

在 Cubie A7Z 的 ST7789V SPI LCD (`/dev/fb0`, 240×280, RGB565) 上使用 EGL/GLES2 渲染旋转三角形。

**当前状态**：已验证通过（2026-05-03），旋转三角形在 LCD 上正常显示。

## 渲染路径

```
EGL surfaceless + Mesa llvmpipe (软渲染)
  → GLES2 绘制三角形
  → glReadPixels 读回 RGBA8888
  → 上下翻转 (OpenGL 原点左下 → fb0 原点左上)
  → RGBA8888 → RGB565 转换
  → mmap 写入 /dev/fb0
```

## 设备环境

| 项目 | 值 |
|---|---|
| 设备 | Radxa Cubie A7Z |
| SoC | Allwinner A733 (sun60iw2) |
| GPU | IMG PowerVR (`img,gpu` @ 0x1800000) |
| LCD | ST7789V, 240×280, 16bpp RGB565, `/dev/fb0` |
| DRM | `/dev/dri/card0` (sunxi-drm) |
| 系统 | Ubuntu 24.04 (aarch64) |

## GPU 驱动状态

- **Kernel 驱动**：IMG PowerVR 已加载（`/sys/devices/platform/soc@3000000/1800000.gpu`）
- **Userspace 驱动**：**缺失**。无 libpvr/libIMG，Mesa 无开源 PowerVR 支持
- **当前回退**：Mesa llvmpipe 软渲染（`EGL_PLATFORM=surfaceless`）

### 已安装的依赖包

```
libegl1 libegl-dev libgles2 libgles-dev
libdrm2 libdrm-dev libgbm1 libgbm-dev
libegl-mesa0 libglapi-mesa libgl1-mesa-dri
```

## 编译与运行

```bash
# 在设备上编译
gcc -o fb_triangle main.c \
    -I/usr/include -L/usr/lib/aarch64-linux-gnu \
    -lEGL -lGLESv2 -ldrm -lgbm -lm \
    -Wl,-rpath,/usr/lib/aarch64-linux-gnu

# 运行（EGL_PLATFORM=surfaceless 已在代码中 setenv）
./fb_triangle

# 停止
killall fb_triangle
```

或使用 `run.sh` 一键推送编译运行。

## 代码结构

| 文件 | 说明 |
|---|---|
| `main.c` | 主程序：fb0 mmap + EGL surfaceless + GLES2 旋转三角形 |
| `run.sh` | adb 推送 + 设备端编译运行脚本 |

### main.c 关键设计

1. **fb0 操作**：`open/mmap /dev/fb0`，通过 `FBIOGET_FSCREENINFO` / `FBIOGET_VSCREENINFO` 获取分辨率和 stride
2. **EGL 初始化**：`setenv("EGL_PLATFORM", "surfaceless", 1)` → PBuffer surface → GLES2 context
3. **GLES2 着色器**：顶点着色器含 `uAngle` uniform 旋转矩阵，片段着色器顶点色插值
4. **渲染循环**：`glDrawArrays` → `eglSwapBuffers` → `glReadPixels` → 翻转 → RGB565 转换 → 写入 fb0
5. **Y 轴翻转**：OpenGL 原点左下角，fb0 原点左上角，逐行交换

## 性能

- 帧率目标：~60fps（`usleep(16000)`）
- 实际瓶颈：llvmpipe 软渲染 + `glReadPixels` 回读 + 逐像素 RGB565 转换
- 240×280 分辨率下软渲染可接受，大分辨率将成瓶颈

## 演进路径

1. **PowerVR userspace 驱动**：部署 Allwinner BSP 提供的 PowerVR ROCm 驱动，启用硬件 GPU 加速
2. **DRM/KMS 渲染**：将 LCD 接入 DRM 管道（`drm/tiny` 驱动），直接 `drmModeSetCrtc` 显示，无需 fb0 blit
3. **零拷贝优化**：使用 GBM buffer + DMA-BUF 共享，避免 `glReadPixels` 回读
