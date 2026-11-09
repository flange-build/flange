## Context

分层接口已就绪：`DistroBackend`（基础系统、App 安装、定制、包清单）、`BuildEnvironmentSpec`（单目标单容器）、
`Toolchain`（profile、`target_sysroot`、`sdk_identity`）、`PackageBackend`（规划/生成/导入/设备命令）。
Debian 示例证明了"同族发行版"可行；Alpine 的 musl、apk、OpenRC 三个差异检验接口是否真正中立。

## Goals / Non-Goals

目标：Luckfox Pico Max 上 Alpine 3.24 启动，串口/SSH 登录；`flange app build/deploy/run/log` 对 C/C++ 与
Python App 可用；默认 adbd + usbmoded 在 OpenRC 下工作；Ubuntu 目标零回归。非目标见 proposal。

## Decisions

1. **init 系统是发行版属性，不是 App 属性。** `DistroBackend.init_system` 返回 `InitSystem` 名称；
   App 为每种 init 各写一份原生服务文件（systemd unit / OpenRC 脚本），不引入自研服务描述语言，
   避免翻译层把 `Type=notify`、`Restart=` 等语义做错。App 构建按目标 init 校验对应文件存在。
2. **包格式由发行版决定默认值。** `DistroBackend.package_format` 给出默认格式，AppSpec 显式写了
   与目标不符的格式时报错；跨发行版共用 App 时依赖按格式分开声明（`packaging.depends.apk`），
   未声明时 apk 包不写依赖，由 rootfs 包集合保证。
3. **apk 包用 `apk mkpkg` 生成。** apk-tools 3（Alpine 3.23+）内置 `mkpkg`，可在 x86_64 环境用
   `apk.static` 为 armv7 生成包，无需 abuild 与签名密钥；安装时 `--allow-untrusted`。
   这是首个验证点，若 mkpkg 产物不被目标 apk 接受，退回纯 Python 生成 v2 包。
4. **musl 工具链用 clang + Alpine sysroot。** Alpine 不提供 x86_64→armv7 交叉 gcc；
   用 flange-build 镜像随 Swift 提供的 clang/lld（实施时 Ubuntu archive 不可用，且无需第二套 LLVM）配合 `apk.static --root <sdk> --arch armv7 --no-scripts add musl-dev gcc g++ ...`
   取得 crt、libgcc、libstdc++ 与头文件，包装成 `armv7-alpine-linux-musleabihf-{gcc,g++}`，
   binutils 用 `llvm-ar/ranlib/strip/objcopy`。SDK 包版本与归档摘要写入 `/opt/flange-sdk-metadata`，
   镜像摘要进入 ABI 身份。这是第二个验证点，失败退回在镜像中构建 musl-cross-make gcc。
5. **init 身份**：非 systemd 目标在 App 报告的用户态身份中记录 `init_system`，
   systemd 目标身份不变，避免既有报告全部失效；设备命令据此生成。
6. **rootfs 基础系统**：minirootfs → 注入 qemu → chroot `apk add`；`/etc/apk/cache` 绑定到按发行版/架构
   隔离的共享缓存。安装 `shadow sudo bash openssh` 后复用核心 `_configure_users`；hostname 通用；
   locale 跳过（musl 无 locale 生成）。OpenRC 服务在 chroot 中 `rc-update add` 启用。
7. **板级 product 由 Alpine 层追加**：上层同名板 `products+: ['alpine']`，`distro` 随 product 选择；
   核心板不知道 Alpine 存在。
8. **usbmoded 服务后端探测**：优先 `NOTIFY_SOCKET`/`/run/systemd/system` 判断 systemd，
   否则使用 `rc-service`；udev 规则中的 reload 改为调用 usbmoded 自带的控制命令。Alpine 侧用 eudev 提供 udev。

## Risks / Trade-offs

- clang + Alpine gcc 运行库混用 → 以真实 C/C++ App 在 QEMU 与实机运行验证，必要时退回 gcc 交叉链。
- apk v3 包格式较新 → 生成后在目标 rootfs 中 `apk add` 与 `apk info -L` 校验。
- usbmoded 改动影响所有 Ubuntu 板 → systemd 分支保持命令序列不变，补单元测试。
- Debian 包名残留在平台层 `custom_packages+:` → Alpine product 显式重置包列表，配置校验拒绝未知包。

## Migration Plan

先核心抽象（Ubuntu 零回归）→ Alpine 层 rootfs → 环境/SDK/apk → App 与 usbmoded → 实机。
每阶段跑全量测试；实机结论单独记录，不以 QEMU 结果冒充硬件验证。
