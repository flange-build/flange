## Context

当前 `components/config/rockchip.libsonnet` 固定下载 9 个 release DEB。四个 GStreamer DEB 直接包含完整 Meson
`DESTDIR`，与 Noble 的 tools、plugins、runtime library 和 GIR 分包发生文件重叠；目标 rootfs 只能强制覆盖并 hold。
flange 已有 package→vendor App→rootfs dpkg 流水线，但一个 App 只能返回一个由 DebBuilder 生成的 DEB，无法表达一次源码
构建产生多个标准 binary package。

## Goals / Non-Goals

**Goals:**

- 将多媒体源码、固定版本、补丁、udev 规则和构建入口集中到一个本地 package。
- 保持 Noble binary package 的文件归属和 control 关系，同时替换为 Rockchip patched 二进制。
- 允许一个 custom App 直接声明多个完整 DEB 输出，并继续由 app/rootfs 既有依赖图安装。
- 让 WebRTC 相关插件成为构建失败即报错的硬要求。

**Non-Goals:**

- 不实现通用 source package builder、APT repository 或 dev SDK 发布。
- 不升级上游版本，不修改 rkwebscr。

## Decisions

### 1. 以 Noble runtime DEB 作为分包模板

构建脚本通过签名 APT 索引下载固定版本 ARM64 DEB，解包后只覆盖 flange 交叉编译 `DESTDIR` 中同路径文件，更新内部版本和
Maintainer、重算 md5sums，再用 `dpkg-deb --root-owner-group` 重打。这样直接复用 Ubuntu 已验证的 package name、Multi-Arch、
Depends、Breaks/Replaces 和 maintainer scripts。

未选择从零维护 `.install` 文件：四个 GStreamer source package 的 binary split 多且会随 Ubuntu 安全修订变化，复制一套会重新
制造当前文件归属错误。未直接安装模板 DEB：ProjectSpec 要求 vendor 内容必须重打为 flange 自有包。

### 2. MPP、RGA 与 Rockchip 插件保持独立 runtime 包

这三项没有 Noble 模板，按实际 `DESTDIR` 分别生成 `rockchip-mpp`、`librga2`、`gstreamer1.0-rockchip`。头文件、pkg-config 和
unversioned linker symlink 只进入构建 sysroot，不安装进目标 rootfs；udev 规则由独立的 `flange-rockchip-multimedia` App 打包。

### 3. AppSpec 新增 `build.deb_outputs`

字段仅允许 `app.type=vendor`、`build.system=custom`，元素必须是输出目录内的安全 `.deb` 文件名。AppBuilder 向 custom 命令传入
`FLANGE_BUILD_ROOT`、`FLANGE_APP_WORK_DIR`、`FLANGE_APP_OUTPUT_DIR`、`FLANGE_TARGET_ARCH`，编译后逐个校验声明文件并直接
返回首个产物，不再生成 wrapper DEB。rootfs 已安装 app 输出目录内全部 DEB，无需新增调度节点。

未新增 `PackageBuilder`：当前只有一个多 DEB 用例，既有 AppBuilder 已覆盖依赖排序、缓存和 rootfs 路由。

### 4. board 显式 opt-in

移除 SoC `rootfs.extra_debs`，在当前受支持的 RK3566/RK3568/RK3576/RK3582/RK3588/RK3588S board 的顶层 `packages`
追加 `rockchip-multimedia`。这保持 ProjectSpec 的 board package policy，并避免未来新板隐式安装大体积多媒体栈。

## Risks / Trade-offs

- [Ubuntu 模板安全版本更新] → 固定模板版本与 `+flange1` 一起测试；升级 Noble 基线时同步更新模板版本并重建。
- [交叉编译可选 feature 静默关闭] → `webrtc`、`dtls`、`srtp`、KMS/Wayland 与 Rockchip feature 使用 Meson `enabled`，并检查
  staging/DEB 内目标 `.so`。
- [模板与自编安装树出现新文件] → 构建脚本拒绝未映射的 runtime library、plugin 或 executable，只允许忽略 headers、`.pc`、
  static library 等 dev 文件。
- [完整 GStreamer 首次构建耗时] → 下载与源码保存在 `.build/sources`，App 内容哈希未变化时复用 app cache。

## Migration Plan

1. 先加入 `deb_outputs` 契约与单元测试，保持现有单 DEB App 行为不变。
2. 导入 package、补丁和构建检查，在一个 RK3588 debug target 完成 DEB 构建与 metadata 验证。
3. 批量切换现有 RK35xx board opt-in，删除 `common.multimediaDebs` 和 SoC `extra_debs` 引用。
4. 解析全部 target、运行测试和 OpenSpec validate；失败时可回退 board package opt-in 并恢复原 `extra_debs`。

## Open Questions

无。dev package 发布和独立 APT 仓库留给实际出现外部 SDK 消费者时处理。
