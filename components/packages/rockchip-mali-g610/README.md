# Mali-G610 厂商 GPU package

供 `radxa-rock5b-rockmedia-debug/release` 使用。ROCK 5B 的产品配置负责同时切换 BSP（板级支持包）
内核驱动与设备树，本包提供 g24p0 X11/Wayland/GBM 的厂商用户态库、GBM hook（兼容层）、
OpenCL/Vulkan ICD（驱动加载描述）、动态链接维护脚本及 `/dev/mali0` 的 video 组权限。

## 输入与交付

输入来自 [libmali-rockchip 固定发布](https://github.com/tsukumijima/libmali-rockchip/releases/tag/v1.9-1-20260312-bd33ee2)，
为 Rockchip 的 Mali-G610 厂商二进制及上游 wrapper（封装库）。准确 URL 和 SHA-256 见
[runtime/build.py](runtime/build.py)，缓存命中同样校验摘要。

构建在 Docker 内提取数据文件，由 flange 的默认 DEB 后端重新生成
`flange-mali-g610_1.9.0+g24p0.flange1_arm64.deb`。不安装上游 DEB、不执行其维护脚本。
保留上游版权文件和发行说明，并记录原始下载地址与摘要。

EGL/GLES/GBM 封装库位于 `/usr/lib/aarch64-linux-gnu/mali/`，由
`/etc/ld.so.conf.d/00-aarch64-mali.conf` 选择。不会覆盖 Ubuntu 的同名公共库文件。
安装、移除后执行 `ldconfig`。不得同时安装另一套 libmali 包。

删除输入 DEB 携带的独立 CSF 固件和全局实时线程优先级设置；固件使用当前 BSP 的
`CONFIG_MALI_CSF_INCLUDE_FW=y` 编译注入版本。

## 使用与边界

```bash
lunch radxa-rock5b-rockmedia-debug
flange build
```

若使用独立工作区，先执行 `flange init <目录> --tool-root <flange仓库>`，进入工作区后选择 target。
该产品继承 `rockchip-multimedia`，包括 MPP、RGA、GStreamer core/base/good/bad、Rockchip 插件、
媒体设备权限，另带 `clinfo`、`eglinfo`、`v4l2-ctl`、`modetest` 等检查工具。

本产品默认是多媒体命令行基座，不启动桌面或 Wayland compositor（合成器）。X11/Wayland 后端的应用
需要另行启动对应显示服务；直接显示可以先验证 DRM/KMS。厂商 EGL/GLES 不能等同于完整桌面 OpenGL。

自编 C/C++ 多媒体 App 应声明 `build.deps`，复用 `rkmm-mpp`、`rkmm-rga`、`rkmm-gstreamer`、
`rkmm-gst-base` 的构建安装树，再用 `flange app build` 在 Docker 中编译。目标镜像默认交付运行库与
命令行开发检查工具；未新增完整板端开发头文件或 SDK 分发，避免混用 Ubuntu dev 包与自编 GStreamer 版本。

## 实机验收

2026-09-16 已完成配置隔离等 36 项回归、OpenSpec 校验、Docker 内 `flange app build`，以及
ARM64 Ubuntu 24.04 干净容器中的安装、`dpkg --audit`、EGL/GLES/GBM/OpenCL 库加载和卸载恢复验证。
现有 RK3588 BSP 的 Kconfig 实际求值确认厂商 GPU、内置 CSF 固件、MPP 和 MULTI_RGA 均启用。
同日已完成 `rockmedia-debug` 完整镜像构建；镜像内 `dpkg --audit`、厂商 GPU 库加载以及
`mppvideodec`、`webrtcbin`、`dtlssrtpenc`、`srtpenc` 注册检查通过。首次 rootfs 构建暴露的
Wayland/XCB 依赖缺失已通过包内 `config.jsonnet` 显式预装全部系统 Depends 修复。
`mpph264enc` 注册会实际调用 MPP 编码器初始化，因此无 Rockchip 硬件的容器中不注册；
ROCK 5B 实机 GPU、RGA、编解码和显示验收仍未完成。

更新现有设备时必须成套更新 boot 和 rootfs；仅编辑 overlay 无法切换 GPU 驱动。
回退也要使用原产品重新构建的 boot/rootfs。刷写命令和分区以 `flange flash --list` 为准。

以默认普通用户运行，确认设备权限与真实硬件路径：

```bash
id
ls -l /dev/mali0 /dev/mpp_service /dev/rga
cat /proc/device-tree/gpu@fb000000/compatible
sudo dmesg | grep -Ei 'mali|kbase|csf|rga|mpp'
dpkg --audit
ldconfig -p | grep -E 'libEGL.so.1|libGLESv2.so.2|libgbm.so.1'
clinfo -l
eglinfo -B
gst-inspect-1.0 mppvideodec
gst-inspect-1.0 mpph264enc
gst-inspect-1.0 webrtcbin
```

设备树节点名以实际 `/proc/device-tree` 为准。`eglinfo` 的未启动 X11/Wayland 后端可能报错；
验收至少一个实际支持的后端，renderer 必须报告 Mali，不能以 llvmpipe（软件渲染器）作为 GPU 成功。
`clinfo` 应枚举 Mali-G610。动态链接输出应指向 `mali/` 封装库。

编码与解码基础验证：

```bash
gst-launch-1.0 -e videotestsrc num-buffers=120 ! \
    video/x-raw,format=NV12,width=1280,height=720,framerate=30/1 ! \
    mpph264enc ! h264parse ! filesink location=/tmp/rockmedia.h264
gst-launch-1.0 filesrc location=/tmp/rockmedia.h264 ! h264parse ! mppvideodec ! fakesink
```

插件注册检查不等于硬件成功；还需分别验证 RGA 缩放/色彩转换、实际输入视频硬解、显示输出与 DMA-BUF
（共享缓冲区）互通。不同显示服务和 DDK（驱动开发套件）组合的兼容性以实机结果为准。
