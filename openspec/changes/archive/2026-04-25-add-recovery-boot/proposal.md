## Why

当前 flange 已能生成可刷写镜像并通过宿主机 USB 工具进行分区级刷写，但设备启动后缺少一个独立的维护环境来执行线刷、备份和分区修复。新增 recovery 引导可以让设备在正常系统不可用或需要在线维护时，进入一个完整一点的 Ubuntu 小系统，通过 USB 线缆完成系统烧录、分区备份和分区刷写，不依赖网线或 Wi-Fi。

## What Changes

- 新增独立的 `recovery` 分区与 `recovery.img` 构建组件，基于 Ubuntu base 构建最小维护系统。
- 新增 recovery 引导入口，使 boot 分区能够提供 normal 和 recovery 两种启动路径。
- 在 recovery rootfs 中预装 `adbd`、分区工具、校验/压缩工具和设备端 `recoveryctl`。
- 新增宿主机命令组 `flange recovery`，提供进入 recovery、列分区、刷分区、备份分区、打开 shell 和重启等线刷操作。
- 首版线刷 transport 使用 ADB over USB，后续可扩展为 USB DFU 或自定义 USB 协议。
- 将 recovery 分区与 recovery 镜像纳入整盘镜像组装和 flash-config 分区镜像映射，使 `flange flash recovery` 与 `flange recovery flash <partition>` 使用同一份分区配置事实源。
- 新增 `/etc/flange/recovery-config.json`，在 recovery 系统内冻结构建时的 board、product、variant、分区布局与安全策略。
- 对分区写入建立安全约束：镜像大小校验、sha256 校验、目标分区未挂载检查、写后校验；bootloader/raw 分区默认禁止通过 recovery 刷写，除非显式强制。

## Capabilities

### New Capabilities

- `recovery-boot`: 定义 recovery 分区、recovery.img 构建、boot 分区双入口、整盘镜像组装和 flash-config 映射。
- `recovery-usb-flash`: 定义 `flange recovery` 宿主机命令、ADB over USB transport、设备端 `recoveryctl` 以及线刷/备份/分区列表行为。

### Modified Capabilities

- 无。现有 `platform-abstraction`、`allwinnera733-flash` 等 capability 的既有要求不直接改变；本变更通过新增 capability 承接 recovery 行为。

## 非目标

- 不实现基于 Ethernet、Wi-Fi、HTTP Web UI 的网络烧录。
- 不在首版实现 USB DFU 或自定义 USB 协议，仅保留 transport 抽象以便后续扩展。
- 不实现 OTA、A/B 分区切换或增量更新。
- 不要求首版支持无物理连接的远程维护场景。
- 不把 recovery 功能混入 normal rootfs；recovery 必须是独立分区和独立 rootfs。

## Impact

- `builder/cache.py`：组件依赖图和必需产物需要增加 `recovery`。
- `builder/engine.py`：需要调度 recovery 构建，并在 image 构建时收集 recovery 产物。
- `builder/platforms/<platform>/`：新增 recovery 构建策略，并扩展 boot/image/flash 映射。
- `components/platform/*/*/config.py`：分区表需要增加 `recovery` 分区，部分平台可能需要调整 `rootfs` 和 `userdata` 偏移。
- `components/app/` 或 `components/packages/`：新增 `recoveryctl` 设备端工具或包定义。
- `envsetup.sh` 和/或 Python CLI：新增 `flange recovery` 命令组。
- `tests/`：新增 recovery 构建、配置生成、CLI transport、`recoveryctl` 分区操作的单元测试和集成测试。
