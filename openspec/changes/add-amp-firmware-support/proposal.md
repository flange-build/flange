## Why

flange 已能构建 Linux 主系统的内核/根文件系统/引导/镜像，但 Rockchip SoC 上的 AMP（Asymmetric Multi-Processing，非对称多处理）协处理器固件完全没有接入：commit `a84e5c52` 只把 Rockchip AMP SDK（`components/amp/rockchip/` 下的 hal 裸机与 rt-thread RTOS 两套源）落盘，`builder/` 全仓 0 处引用。用户需要在同一片 RK35xx 上让 Linux 主系统与一个实时协处理器核（一个 Cortex-A55 切到 AArch32 跑裸机或 RT-Thread）协同工作，因此要求 flange 能**构建出含 `amp.img` 的固件、把它刷进设备、并让 Linux 用户态 app 与协处理器通信**，同时在 flange app 体系里支持创建 AMP app 工程。

## What Changes

- **新增 `amp` 一等构建组件**：在依赖图中注册 `amp` 节点（仿 `recovery`/`app`），按配置 `amp.mode`（`hal` | `rt-thread` 二选一）在 Docker 容器内驱动 SDK 的 `build.sh` + `mkimage`（hal 路径）或 `scons` + `mkimage`（rt-thread 路径），产出 FIT 格式的 `amp.img`，并接入产物收集、增量缓存与 `image` 组装。
- **新增 `amp` app 类型**：扩展 `flange create app --type amp` 脚手架与 `app.yaml` 规格，承载用户在 hal/rt-thread 之上的应用逻辑；amp app 走独立裸机构建链，**不打 deb、不进 rootfs**。
- **新增非 raw 的 `amp` GPT 分区与刷写接线**：在分区表声明 `amp` 分区（**必须为非 raw 具名分区**，否则 U-Boot 按分区名定位失败），接入 `image.py` 整盘组装与 `flash.py` 刷写映射，使 `flange build` 产出含 amp 分区的镜像、`flange flash amp` 可单刷。
- **打通端到端启动与通信**：开启 U-Boot `CONFIG_AMP`（bootloader defconfig patch）让 U-Boot 从 amp 分区加载 FIT 并拉起从核；给目标板配一个**专用 AMP dts 文件**（`#include "rk3568-amp.dtsi"` 接入 reserved-memory / rockchip-amp / rpmsg / `&mailbox` + `/delete-node/ &cpu3;` 把第 4 核摘给 AMP，启用后 Linux 跑 3 核 + AMP 从核 console 用 UART4，零固件改动），由 amp product 选用；内核补 `CONFIG_RPMSG_CHAR=y` + `CONFIG_RPMSG_CTRL=y`，使用户态 app 经 `/dev/rpmsg_ctrlN`、`/dev/rpmsgN` 直接收发。
- **Docker 构建镜像新增裸机工具链**：加入 newlib 版 `arm-none-eabi-` 工具链（钉 gcc-10），现有的 `arm-linux-gnueabihf`/`aarch64-linux-gnu`（glibc）无法编译需要 `--specs=nosys.specs` 的裸核固件。
- **修正增量缓存盲区**：`amp` 源在 `components/amp/` 仓库内、不走 `.build/sources`，需为其补目录内容哈希，否则改 SDK/应用源不触发重建（假命中）。
- **建立内存布局单一事实源**：`CPUn_MEM_BASE` / `SHMEM_BASE` / `LINUX_RPMSG_BASE` 等地址常量在 SoC 配置中定义一次，构建期注入 `build.sh`、`amp_linux.its`、kernel DTS 三方，逐字节一致（SDK 自带示例值本身不自洽，不能沿用；DTS 腿走静态 patch 故由交叉校验保障）。

首板范围：**tspi-rk3566**（与 rk3568 同 die、同 4×A55，复用 rk3568 工程与 `rk3568-amp.dtsi`），产品形态为 **Linux（3 核）+ 1 个 A55 从核**（cpu3，用 `amp_linux.its`）。承载方式为 tspi-rk3566 的 **`amp` product**（lunch `tspi-rk3566-amp`）：amp product 选用专用 amp dts、开 amp.enabled/mode，`default` product 不受影响。

## Capabilities

### New Capabilities

- `amp-firmware-build`: `amp` 构建组件——依赖图注册、`mode`（hal|rt-thread）二选一在容器内构建并经 `mkimage` 打成 FIT `amp.img`、产物收集与改名、`enabled` 开关、`components/amp/` 源码增量哈希、内存布局单一事实源注入。
- `amp-app-scaffold`: `amp` app 类型——`VALID_APP_TYPES`/`VALID_BUILD_SYSTEMS` 扩展、`flange create app --type amp` 脚手架与模板、`app.yaml` 规格、独立构建路径（不打 deb / 不进 rootfs）与独立的 amp app 收集声明键。
- `amp-partition-flash`: `amp` 固件的落盘与刷写——非 raw 具名 `amp` GPT 分区声明、`image.py` 整盘组装 dd 写入、`flash.py` 刷写映射与 `amp.enabled` gate、`validate_amp` 配置校验（`mode` 枚举 + amp 分区存在）。
- `amp-runtime-bringup`: 端到端启动与通信——U-Boot `CONFIG_AMP`/`CONFIG_ROCKCHIP_AMP` 加载从核、board kernel patch 接入 Linux DTS 的 AMP/rpmsg/mailbox 节点、内核 `RPMSG_CHAR`/`RPMSG_CTRL` 暴露 `/dev/rpmsg*` 字符设备。

### Modified Capabilities

- `docker-build-env`: 新增「容器内必须具备裸机 ARM 工具链（`arm-none-eabi-`，newlib，提供 `--specs=nosys.specs`）」要求，使 amp 固件可在构建容器内编译；现有 glibc 交叉工具链要求不变。

## Impact

- **构建引擎**：`builder/cache.py`（`DEPENDENCY_GRAPH`/`REQUIRED_ARTIFACTS`/`compute_hash`）、`builder/engine.py`（`_component_disabled`）、`builder/platforms/rockchip/__init__.py`（`create_builder`/`ARTIFACT_NAMES`）、新建 `builder/platforms/rockchip/amp.py`。
- **App 体系**：`builder/app_spec.py`、`builder/scaffold.py`、`builder/app.py`、新建 `builder/templates/amp/`、amp app 收集声明键（不污染 `rootfs.custom_packages`）。
- **分区与刷写**：`components/platform/rockchip/rk3566/config.py` 分区表（仅 rk3566，不动在用的 rk3568 板）、`builder/platforms/rockchip/image.py`（`PARTITION_IMAGES`）、`builder/flash.py`（`partition_image_map`）、`builder/config/validate.py`。
- **启动 / 内核 / DTS**：`components/platform/rockchip/patches/bootloader/`（U-Boot `CONFIG_AMP`）、`components/board/tspi-rk3566/patches/kernel/`（**新增**专用 amp dts 文件：amp dtsi + `/delete-node/ &cpu3;` + UART4）、`components/platform/rockchip/rk3566/config.py`（内存布局常量 + `soc_project`）。
- **配置开关**：`components/platform/rockchip/config.py`（amp 默认关）、`components/board/tspi-rk3566/config.py`（`products` 加 `amp`，amp product 条件键开 amp.enabled/mode、选 amp dts、追加 `RPMSG_CHAR/CTRL`）。
- **Docker**：`docker/Dockerfile`（裸机工具链）。
- **依赖**：新增对 SDK 自带 `tools/mkimage`（x86-64 ELF，无需额外装 u-boot-tools）与官方 gcc-arm-none-eabi-10 的构建期依赖。
- **运行时基座已就绪**（无需改动）：内核 `MAILBOX`/`ROCKCHIP_MBOX`/`RPMSG_ROCKCHIP_MBOX`/`RPMSG_VIRTIO`/`ROCKCHIP_AMP` 已 `=y`；U-Boot AMP loader 源码已在树；内核树自带 `rk3568-amp.dtsi` 参考节点。

## 非目标

- **不支持 per-core 混装**：本轮 `amp.mode` 为整张 `amp.img` 单一来源（hal 或 rt-thread）二选一；SDK 实证支持同一 amp.img 不同核混装 hal/rtt，但暂不暴露该粒度，单核是退化情形。
- **不接入独立 MCU 核路径**：`*-mcu`（Cortex-M0 / RISC-V）走 OSA 分区 + `firmware_merger`/`upgrade_tool` 的另一套刷写链路，本轮不覆盖；仅做 A55 AArch32 从核（amp.img + U-Boot FIT 加载）。
- **不引入安全启动 / FIT 签名链**：默认产出未签名 `amp.img`，仅验证目标 U-Boot 不强制 FIT 校验；配置 dev key 的签名链留待后续。
- **不做多板普及**：首版仅打通 tspi-rk3566（复用 rk3568 工程）；其他 Rockchip 板与其他平台（Allwinner/Amlogic/Qualcomm）的 AMP 不在范围内。
- **不重构既有 app 的 deb 打包链路**：amp app 在 `type` 维度旁路分叉，不改动现有 exec/service/lib/test 四类 app 的构建与打包行为。
