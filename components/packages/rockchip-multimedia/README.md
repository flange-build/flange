# Rockchip 多媒体 package

本 package 在 flange Docker 构建容器内为 AArch64 交叉编译以下 runtime：

- Rockchip MPP 1.3.9
- Rockchip RGA 2.1.0
- GStreamer 1.24.2 core、base、good、bad（带 Rockchip 补丁）
- `gstreamer1.0-rockchip` MPP/RGA/KMS 插件
- MPP/RGA/DMA Heap udev 权限规则

GStreamer 不再把完整 `DESTDIR` 塞进四个粗粒度 DEB。构建器使用 Ubuntu 24.04 Noble ARM64 runtime DEB 作为分包模板，
只覆盖 flange 自编的同路径文件，再重打为 `+flange1` 版本。包名、文件归属、Multi-Arch、Depends 和 Breaks/Replaces 因而
保持 Noble 契约，目标 rootfs 不需要 `--force-overwrite` 或 APT hold。

## 启用

board 在顶层 `packages` 中显式加入：

```jsonnet
packages: ['rockchip-multimedia'],
```

随后执行正常构建：

```bash
lunch <board>-<product>-<variant>
flange build app
flange build rootfs
```

首次构建会下载固定版本的 GStreamer tarball 和三个 Rockchip git revision，缓存位于 `.build/sources/`。中间产物位于
`.build/work/apps/rockchip-multimedia-build/`，DEB 位于当前 target 的 `app/` 目录。

## 验证

本迁移已在 flange 构建容器完成 AArch64 交叉构建，并在干净的 Ubuntu 24.04 ARM64 容器中通过一次性 APT 安装、
`dpkg --audit` 与下列四项 `gst-inspect-1.0` 检查。尚未生成完整目标板 rootfs，也未在 Rockchip 实机验证 VPU、RGA、
KMS 或显示输出；这些硬件验证应在目标板安装镜像后执行。

```bash
python3 components/packages/rockchip-multimedia/tests/check_package.py \
    .build/target/<board>/<product>/<variant>/app
```

目标机安装后还需检查：

```bash
dpkg --audit
gst-inspect-1.0 webrtcbin
gst-inspect-1.0 dtlssrtpenc
gst-inspect-1.0 srtpenc
gst-inspect-1.0 mppvideodec
```

当前只发布目标 rootfs 需要的 runtime 包。头文件与 pkg-config 文件只保留在构建 sysroot；出现独立 SDK 消费者后再增加 dev
产物通道。
