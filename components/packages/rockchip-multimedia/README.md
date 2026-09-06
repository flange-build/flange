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

首次构建会下载固定版本的 GStreamer tarball 和三个 Rockchip git revision，缓存位于 `.build/sources/`（跨单元共享）。
各单元的中间产物位于 `.build/work/apps/<单元名>/<arch>/`，DEB 位于当前 target 的 `app/` 目录。

## 单元拆分

这条编译链拆成 8 个单元 App，每个由 flange 的 per-App 缓存独立判定是否重建 —— 改一个补丁只重编相关单元与其下游：

| 单元 | 类型 | 编译期依赖 | 交付 |
|------|------|-----------|------|
| `rkmm-mpp` | vendor | — | `rockchip-mpp` |
| `rkmm-rga` | vendor | — | `librga2` |
| `rkmm-gstreamer` | staging | — | 仅 staging 树 |
| `rkmm-gst-base` | staging | gstreamer | 仅 staging 树 |
| `rkmm-gst-good` | staging | gstreamer, base | 仅 staging 树 |
| `rkmm-gst-bad` | staging | gstreamer, base | 仅 staging 树 |
| `rkmm-gst-rockchip` | vendor | mpp, rga, gstreamer, base | `gstreamer1.0-rockchip` |
| `rkmm-gst-repack` | vendor | 四个 gst staging 单元 | 14 个 Noble 模板 deb |

`staging` 类型的单元不打 deb、不进 rootfs，只把 DESTDIR 安装树留在自己的工作目录供下游 configure 使用（见 `app.yaml`
的 `build.staging`，它进产物门禁：被删会让上游重建而不是让下游编译失败）。

重打之所以是独立单元：Noble 的分包边界与编译单元边界并不重合 —— `gstreamer1.0-plugins-good` 的两个 deb 里实际含有来自
`gst-plugins-bad` staging 的文件，所以必须等四个单元全部就绪后一次性重打。

构建逻辑集中在 `lib/`（`toolkit.py` 编译单元、`repack.py` 模板重打、`unit.py` 入口），单元目录下只有一份 `app.yaml`。

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
