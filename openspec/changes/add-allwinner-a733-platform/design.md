## Context

flange 使用 Python 构建引擎（`builder/engine.py`）按依赖图调度组件构建。当前仅有 Rockchip 平台实现，平台通过 `importlib.import_module(f"builder.platforms.{platform}")` 动态加载，但配置注册表、产物映射、刷写配置生成器中存在 Rockchip 硬编码。

Allwinner A733 (sun60iw2p1) 是一颗新一代 Allwinner SoC，Radxa Cubie A7Z 是基于此 SoC 的目标板。其构建链与 Rockchip 有显著差异：内核需要外部 BSP 驱动集成和独立 DTS 仓库，bootloader 依赖 Allwinner 专有工具链（6+ 子模块），SD 卡分区布局不同。

## Goals / Non-Goals

**Goals:**
- 消除框架中的 Rockchip 硬编码，使平台扩展仅需添加配置文件和构建器模块
- 完整支持 Allwinner A733 平台的内核编译、boot 分区组装、rootfs 构建、整盘镜像生成
- 支持 SD 卡 dd 刷写
- 保持现有 Rockchip 平台完全不受影响

**Non-Goals:**
- 不从源码构建 Allwinner bootloader（预编译固件模式）
- 不支持 UFS/eMMC 刷写（仅 SD 卡）
- 不修改依赖图结构（kernel→boot/rootfs→image 保持不变）

## Decisions

### D1: 配置注册表自动发现

**选择**: 将 `config/registry.py` 中的硬编码映射表替换为自动扫描 `platform/*/config.py` 和 `platform/*/*/config.py`（SoC 层）。

**替代方案**: 手动扩展映射表 — 每次新增平台/SoC 需修改 registry.py，违反开闭原则。

**实现**: 扫描 `platform/` 目录结构。平台目录需包含 `config.py` 导出 `PLATFORM` 变量，SoC 子目录需包含 `config.py` 导出 `SOC` 变量。SoC 目录的 parent 决定其所属平台。

```
platform/
├── rockchip/
│   ├── config.py          → PLATFORM dict
│   └── rk3566/
│       └── config.py      → SOC dict
└── allwinner/
    ├── config.py          → PLATFORM dict
    └── a733/
        └── config.py      → SOC dict
```

### D2: 产物映射提取至平台

**选择**: 将 `engine.py` 中的 `_ARTIFACT_NAMES` 移至各平台 `__init__.py`，engine 通过平台模块的 `ARTIFACT_NAMES` 常量获取。

**理由**: 不同平台产物名不同（Rockchip 有 `miniloader`，Allwinner 有 `boot_package`）。

**实现**: 各平台 `__init__.py` 导出 `ARTIFACT_NAMES` dict。engine 在 `_collect_artifacts` 时通过 `importlib.import_module(f"builder.platforms.{platform}").ARTIFACT_NAMES` 获取映射。如平台未定义，fallback 到使用源文件原始文件名。

### D3: Flash 策略完全由平台声明

**选择**: `FlashConfigGenerator.generate()` 中的 `pre_flash` 逻辑从 `if platform == "rockchip"` 改为调用 `FlashStrategy.generate_pre_flash_config()` 方法。

**实现**: 在 `FlashStrategy` 基类新增 `generate_pre_flash_config(config) -> PreFlashConfig` 抽象方法。各平台实现自己的 pre_flash 配置生成。

### D4: Allwinner 内核构建（BSP 集成模式）

**选择**: `AllwinnerKernelBuilder` 在标准生命周期中增加 BSP 集成步骤。

**流程**:
1. `ensure()` — 获取内核源码、BSP 仓库、device 仓库（三个独立源码）
2. BSP 集成 — 将 BSP 仓库 symlink 为内核树的 `bsp/` 目录
3. DTS 复制 — 将 device 仓库的 `board.dts` 复制到 `arch/arm64/boot/dts/allwinner/<dts_name>.dts`
4. DTSI 链接 — 将 BSP 的 `configs/linux-5.15/*.dtsi` 链接到内核 DTS include 路径
5. Patch 应用 — 应用 Radxa 补丁（DTB Makefile 注册、header 路径修复等）
6. `configure()` — `make defconfig radxa.config`（两步 defconfig 合并）
7. `compile()` — `make Image modules allwinner/sun60i-a733-cubie-a7z.dtb`
8. `collect()` — Image + DTB + modules

**源码配置**:
```python
"kernel": {
    "repo": "https://github.com/radxa/kernel.git",
    "branch": "allwinner-aiot-linux-5.15",
    "defconfig": ["defconfig", "radxa.config"],   # 列表表示多步合并
    "dts": "sun60i-a733-cubie-a7z",
    "dts_dir": "allwinner",
},
"kernel_bsp": {
    "repo": "https://github.com/radxa/allwinner-bsp.git",
    "branch": "cubie-aiot-v1.4.6",
},
"kernel_device": {
    "repo": "https://github.com/radxa/allwinner-device.git",
    "branch": "device-a733-v1.4.6",
    "board_dts_path": "configs/cubie_a7z/linux-5.15/board.dts",
},
```

**替代方案**: 将 BSP + kernel + device 三个仓库预合并为一个 — 增加维护成本，无法跟踪上游更新。

### D5: Allwinner Bootloader（预编译固件模式）

**选择**: 创建 Allwinner 固件仓库，`AllwinnerBootloaderBuilder` 只拉取预编译固件，不做编译。

**固件仓库结构**:
```
allwinner-firmware/
├── a733/
│   ├── boot0_sdcard.bin      # 已 patch 的 SD 卡 SPL
│   ├── boot0_ufs.bin         # 已 patch 的 UFS SPL
│   └── boot_package.fex      # U-Boot + BL31 + SCP 打包
```

**AllwinnerBootloaderBuilder 实现**:
- `build()` 跳过 source.ensure/reset/patch/configure/compile
- 直接从固件仓库目录 collect 预编译二进制
- 产物: `boot0_sdcard.bin`, `boot0_ufs.bin`, `boot_package.fex`

**理由**: Allwinner bootloader 从源码构建需要 7-8 个子模块、Linaro ARM 7.2.1 (32-bit) 工具链、RISC-V 工具链（SCP 编译）、Allwinner 专有打包工具（update_boot0, dragonsecboot, script 等）。复杂度极高且产物变化频率低。

### D6: SD 卡分区布局

**选择**: Allwinner A733 SD 卡分区表配置：

```python
"partitions": {
    "format": "gpt",
    "sector_size": 512,
    "entries": [
        {"name": "boot0",         "offset": "0x100",  "size": "0x700",   "type": "raw"},
        {"name": "boot0_ufs",     "offset": "0x810",  "size": "0x700",   "type": "raw"},
        {"name": "boot_package",  "offset": "0x6000",  "size": "0x2000",  "type": "raw"},
        {"name": "boot",          "offset": "0x8000",  "size": "0x20000", "type": "ext4"},
        {"name": "rootfs",        "offset": "0x28000", "size": "0x200000","type": "ext4"},
    ],
}
```

### D7: Boot 分区布局

**选择**: Allwinner 的 boot 分区将文件放在 `extlinux/` 子目录下（与 Rockchip 不同）。

```
Allwinner boot 分区:
  /extlinux/extlinux.conf
  /extlinux/Image
  /extlinux/sunxi.dtb         ← DTB 重命名为 sunxi.dtb

Rockchip boot 分区:
  /extlinux/extlinux.conf
  /Image
  /dtb/rockchip/<name>.dtb
```

`AllwinnerBootBuilder` 实现对应的 staging 布局和 extlinux.conf 生成。DTB 文件名在 config 中通过 `boot.dtb_filename` 配置（默认 `sunxi.dtb`）。

### D8: Source Manager 扩展

**选择**: 扩展 `SourceManager` 支持多源码仓库的 ensure。

当前 `source.ensure(component, config)` 一个组件只对应一个源码目录。Allwinner 内核需要三个仓库（kernel, bsp, device）。

**方案**: 新增 `source.ensure_extra(name, config_section)` 方法用于获取额外仓库。`AllwinnerKernelBuilder` 在 build 流程中调用：
```python
kernel_dir = self.source.ensure("kernel", config)
bsp_dir = self.source.ensure_extra("kernel_bsp", config.get("kernel_bsp", {}))
device_dir = self.source.ensure_extra("kernel_device", config.get("kernel_device", {}))
```

## Risks / Trade-offs

### [Risk] BSP 与内核版本耦合
BSP 仓库的 branch (cubie-aiot-v1.4.6) 与内核 branch (allwinner-aiot-linux-5.15) 必须版本匹配。
→ **缓解**: 在 SoC 配置中将 BSP 和 kernel branch 绑定声明，升级时同步更新。

### [Risk] 预编译固件需要手动更新
boot0 和 boot_package.fex 作为预编译二进制存放在固件仓库，不会自动跟随 U-Boot 源码更新。
→ **缓解**: 固件仓库使用 commit pin，更新时有明确的版本记录。未来可考虑在 CI 中自动构建。

### [Risk] DTSI include 路径复杂
board.dts 通过 `#include "sun60iw2p1.dtsi"` 引用 BSP 中的 DTSI，但 DTSI 存放在 `bsp/configs/linux-5.15/`，不在标准内核 DTS include 路径中。
→ **缓解**: 构建前将 BSP DTSI 文件 symlink 到 `arch/arm64/boot/dts/allwinner/` 目录。

### [Trade-off] 自动发现 vs 显式注册
自动发现平台/SoC 配置减少了硬编码，但也意味着错误的目录结构可能导致静默失败。
→ **缓解**: 发现时做基本校验（config.py 存在性、必需变量检查），发现失败时给出明确错误信息。

## Open Questions

1. **Allwinner 固件仓库托管位置**: 是新建 Git 仓库，还是放在 flange 项目内的 `firmware/allwinner/` 目录？建议新建仓库以隔离二进制和源码。
2. **Radxa patches 管理方式**: 当前 Radxa 使用 debian/patches 格式。flange 是否应该将这些 patches 放在 `platform/allwinner/patches/kernel/`？还是作为 BSP 集成的一部分自动处理？建议放在 platform patches 目录，复用现有补丁机制。
