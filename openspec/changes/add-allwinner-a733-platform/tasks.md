## 1. 平台抽象重构

- [x] 1.1 重构 `config/registry.py` — 将 `_PLATFORM_CONFIGS` 硬编码映射替换为自动扫描 `platform/*/config.py`，将 `_SOC_CONFIGS` 替换为自动扫描 `platform/*/*/config.py`（排除 `__pycache__` 等非配置目录）
- [x] 1.2 重构 `builder/engine.py` — 将 `_ARTIFACT_NAMES` 从 engine 硬编码提取到各平台 `__init__.py` 的 `ARTIFACT_NAMES` 常量，engine 通过 `importlib` 动态获取
- [x] 1.3 重构 `builder/flash.py` — 在 `FlashStrategy` 基类新增 `generate_pre_flash_config(config) -> PreFlashConfig` 抽象方法，`RockchipFlashStrategy` 实现返回 miniloader 配置，`FlashConfigGenerator.generate()` 改为调用策略方法
- [x] 1.4 验证重构 — 确认现有 Rockchip 平台（radxa-zero3w, tspi-rk3566）的 `resolve_config`、engine 产物收集、flash-config 生成行为与重构前完全一致

## 2. Allwinner 平台配置

- [x] 2.1 创建 `platform/allwinner/config.py` — 定义 PLATFORM 字典（vendor, flash_tool, arch, products, variants, rootfs packages 等），不含 rkbin 相关配置
- [x] 2.2 创建 `platform/allwinner/a733/config.py` — 定义 SOC 字典（SoC 标识、内核仓库/分支/defconfig、BSP 仓库、device 仓库、固件仓库、分区表、boot 参数、rootfs URL）
- [x] 2.3 创建 `board/radxa-cubie-a7z/config.py` — 定义 BOARD 字典（board/soc/platform 标识、kernel DTS 名、板级特定配置覆盖）
- [x] 2.4 验证配置 — 确认 `discover_boards()` 能发现 radxa-cubie-a7z，`resolve_config("radxa-cubie-a7z", "default", "debug")` 三层合并结果正确

## 3. Source Manager 扩展

- [x] 3.1 在 `builder/source.py` 新增 `ensure_extra(name, config_section)` 方法，支持获取额外仓库（BSP、device 等），存储在 `sources/extra/<name>/` 目录
- [x] 3.2 验证 — 确认 ensure_extra 支持 repo/branch/commit 配置，与现有 ensure 逻辑一致

## 4. Allwinner 内核构建器

- [x] 4.1 创建 `builder/platforms/allwinner/kernel.py` — 实现 `AllwinnerKernelBuilder`，override `build()` 增加 BSP 集成步骤：symlink BSP 到内核 `bsp/`，复制 board DTS，链接 BSP DTSI
- [x] 4.2 实现多步 defconfig 合并 — 当 `kernel.defconfig` 为列表时，按顺序执行每个 make target
- [x] 4.3 实现 compile 和 collect — 编译 Image + DTB + modules，collect 返回三项产物路径

## 5. Allwinner Bootloader 构建器

- [x] 5.1 创建 Allwinner 固件仓库（或目录）— 存放 A7Z 的 `boot0_sdcard.bin`、`boot0_ufs.bin`、`boot_package.fex` 预编译二进制
- [x] 5.2 创建 `builder/platforms/allwinner/bootloader.py` — 实现 `AllwinnerBootloaderBuilder`，override `build()` 跳过编译，直接从固件仓库 collect 预编译产物

## 6. Allwinner Boot 构建器

- [x] 6.1 创建 `builder/platforms/allwinner/boot.py` — 实现 `AllwinnerBootBuilder`，生成 extlinux/ 布局的 boot.img（Image + sunxi.dtb + extlinux.conf 均在 /extlinux/ 下）
- [x] 6.2 实现 extlinux.conf 生成 — 支持 `boot.dtb_filename`（默认 `sunxi.dtb`）和 `boot.kernel_args` 配置

## 7. Allwinner Rootfs 构建器

- [x] 7.1 创建 `builder/platforms/allwinner/rootfs.py` — 实现 `AllwinnerRootfsBuilder`，继承 `RootfsBuilder` 基类，复用两阶段缓存、overlay、firmware 等通用能力
- [x] 7.2 实现 fstab 生成 — 适配 Allwinner 分区标签和挂载点（与 Rockchip 可能相同，需确认 root 分区定位方式）

## 8. Allwinner Image 构建器

- [x] 8.1 创建 `builder/platforms/allwinner/image.py` — 实现 `AllwinnerImageBuilder`，将 boot0、boot_package、boot.img、rootfs.img 按 SD 卡分区表 dd 到 raw.img
- [x] 8.2 处理 Allwinner 特殊的 raw 分区布局 — boot0 写入 sector 256，boot0_ufs 写入 sector 2064，boot_package 写入 sector 24576

## 9. Allwinner 平台工厂和 Flash 策略

- [x] 9.1 创建 `builder/platforms/allwinner/__init__.py` — 实现 `create_builder()` 工厂函数和 `ARTIFACT_NAMES` 常量
- [x] 9.2 在 `builder/flash.py` 新增 `AllwinnerFlashStrategy` — 实现 SD 卡 dd 刷写策略，注册到 `_FLASH_STRATEGIES`
- [x] 9.3 实现 `AllwinnerFlashStrategy.partition_image_map()` — 返回 Allwinner 分区到镜像路径的映射

## 10. 集成验证

- [ ] 10.1 端到端验证 — 确认 `flange build` 对 radxa-cubie-a7z 目标完整走通 kernel → boot → rootfs → image 流程，生成 raw.img
- [ ] 10.2 SD 卡刷写验证 — 将 raw.img dd 到 SD 卡，在 A7Z 板上验证启动
- [x] 10.3 回归验证 — 确认 Rockchip 平台（radxa-zero3w）构建和刷写不受影响
