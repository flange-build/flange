# rockchip 平台

> 阅读前提：先读[架构总览](../build-system-design.md)，并从[板卡索引](../boards/README.md)确认型号。
> 本页说明平台机制与已确认的适配约束；芯片支持、产物可构建和实机验收是不同边界。
> 当前操作见[开发指南](../development-guide.md)，扩展步骤见[扩展指南](../extension-guide.md)。

## 概述

Rockchip 系列平台，覆盖 ARM32 RK3506B / RV1106 与 ARM64 RK3566/RK3568/RK3576/RK3588(S)。同一策略层按配置选择 extlinux/FIT、ext4/UBI、块设备 GPT/SPI NAND MTD；[atk-rk3506b](../boards/atk-rk3506b.md) 已完成全刷与冷启动实机验收。

## 关键设计要点

**策略类布局（`builder/platforms/rockchip/`）**

组件策略文件 + 工厂入口：`kernel.py`、`bootloader.py`、`rootfs.py`、`boot.py`、`recovery.py`、`image.py`、`amp.py`，由 `__init__.py:create_builder()` 按组件名分发。`ARTIFACT_NAMES` 表定义 collect key → 产物文件名映射。

**平台数据（`components/platform/rockchip/`）**

- `config.jsonnet`：第一层（platform 层），声明 `vendor`、`flash_tool: "upgrade_tool"`、`architecture`、共享 `sources`、rkbin 与 packages 基线
- SoC 层声明 rkbin、U-Boot/kernel 架构与工具链、boot/rootfs 格式和 AMP runtime。RK3506B 走 ARM32 gcc-10、vendor FIT、UBI；RK3566 与 RK3568 虽同 die，仍须分别选择 1056/1560MHz DDR ini。
- 第三层（board 层）：位于 `components/board/<board>/config.jsonnet`，三层由 Jsonnet object 运算组合

**多媒体由板卡显式启用**

[rockchip-multimedia](../../components/packages/rockchip-multimedia/README.md) 功能包在 Docker 中
构建 MPP 1.3.9、RGA 2.1.0、带补丁的 GStreamer 1.24.2 与 Rockchip 插件，再重打本地 DEB。
是否安装由板级 `packages` 决定，不是所有 SoC 默认下载同一组二进制包。
`rockmedia` 的 Mali-G610 用户态还要求配套 BSP 内核驱动，见 [ROCK 5B](../boards/radxa-rock5b.md)。

**内核与 GPU**

当前平台默认源码分支为 `linux-6.1-stan-rkr5.1`，具体版本可由 SoC/板覆盖。
RV1106 各发行版统一使用固定的 Luckfox SDK Linux 5.10.160，内核位于 SDK 的
`sysdrv/source/kernel`；多媒体模块与实机边界见 [Luckfox 板卡说明](../boards/luckfox-pico-pro-max.md#多媒体驱动与运行时)。
RK3506B 与 RV1106 为 ARM32，采用 vendor FIT 与 UBI；ARM64 块设备通常采用 extlinux 与 ext4。
RK3566/3568/3576 通过 `panfrost.config` 选择 Panfrost；RK3588/3588S 默认通过
`rk3588_panthor.config` 选择 Panthor，固件由规范 `source: {name, subpath}` 引用 BSP 中的 CSF blob。
RK3582 的 GPU 已熔断；板级产品可以显式替换 GPU 栈，不应仅根据分支名推断驱动。

**刷写工具：`upgrade_tool`**

块设备走 `LD → DB → SSD(可选) → WL/DI → RD`；SPI NAND 全刷走 `DB → RCI/RFI/RID 身份门禁 → UL -noreset → DI -p parameter.txt → 具名 DI → RD`。参数文件、摘要、分区大小和 `rootfs_mtd_index` 在任何持久写入前校验；宿主机直接调用，不进 Docker。

**patches**

`components/platform/rockchip/patches/` 下有 `bootloader/`、`kernel/` 两类补丁目录；board 层也可有同名补丁目录，构建器依次应用。

## 宿主 upgrade_tool

截至 2026-11-13，核对 Khadas 与 Luckfox 官方公开分发后，两端收录版本均为 v2.44。
`flange flash` 按宿主系统选择下表路径，无需重新构建 Docker 或目标固件。

| 宿主 | 工具与来源记录 | 可执行架构 |
| --- | --- | --- |
| Linux | [Linux 工具目录](../../tools/linux/upgrade_tool/README.md) | x86_64，静态 ELF |
| macOS | [macOS 工具目录](../../tools/macos/upgrade_tool/README.md) | 通用 Mach-O：x86_64、arm64 |

完成[开发环境准备](../development-guide.md)后，在 flange 仓库根目录执行以下命令。
二进制由 Git LFS（大文件存储）管理，若运行时报格式错误，先确认文件没有停留在 LFS 指针状态：

```bash
git lfs pull --include="tools/*/upgrade_tool/upgrade_tool"
case "$(uname -s)" in
    Darwin) tool=tools/macos/upgrade_tool/upgrade_tool ;;
    Linux) tool=tools/linux/upgrade_tool/upgrade_tool ;;
esac
"$tool" -v
"$tool" -h
"$tool" LD
python -m pytest tests/builder/test_rockchip_tools.py tests/builder/test_flash.py
```

版本查询应输出 `Upgrade Tool v2.44`；`LD` 只枚举设备，输出 `List of rockusb connected(n)`。
未发现设备时按[对应板卡说明](../boards/README.md)检查 USB 连接与下载模式；Linux 还需有
Rockusb 设备访问权限。确认设备后，按[刷写指南](../development-guide.md#4-刷写与设备验证)
使用 `flange flash`，由生成的清单约束写入范围。

更新工具时保留原始配置、修订记录和使用手册，先核对固定提交的 Git 对象或官方发布摘要，
再更新各目录的 `manifest.json` 文件摘要。完整性测试检查全部随附文件、可执行权限和宿主架构。
厂商文本保留原始换行与空格，避免改变其摘要。

2026-11-13，完整 Python 测试集结果为 2148 项通过、15 项跳过。
宿主工具验证不绑定板卡 target：Linux 6.8.0 x86_64 上版本查询、帮助与
`LD` 均成功，枚举结果为 0 台；未进行固件写入。macOS 已检查双架构文件头与系统库依赖，
最低系统声明为 Intel 10.15、Apple Silicon 11.0，尚未完成 Mac 原生执行与 USB 刷写验证。
这些检查不替代各板卡的实机验收。

## 易踩坑

- rkbin 的 `RKTRUST.ini` 区分 BL31/BL32；RK3566 使用 `RK3568TRUST.ini`（ini_prefix 与 trust_ini_prefix 不同，见 `rk3566/config.jsonnet`）
- DTB target 使用子目录相对路径（`rockchip/<dts>.dtb`），非内核完整路径，详见 [kernel 构建器](../components/kernel.md)
- RK3588 板不要用 vendor `<board>-rk3588_defconfig`（含 androidboot 风格固定 bootargs，绕过 extlinux），统一用 generic `rk3588_defconfig`
- **真 RK3568 板必须挂 rk3568 SoC** 不是 rk3566：两者同 die，但 rkbin 的 `RK3568MINIALL.ini` 选 1560MHz DDR、`RK3566MINIALL.ini` 选 1056MHz，挂错砍 33% 性能
- 平台补丁需与当前源码上下文匹配；缺少 context 的 hunk 曾导致模糊应用错位。遇到补丁解析或上下文错误，应重新核对原文件和补丁，不能把模糊匹配成功视为行为验证。
- **RK356x NPU 供电**：`rk356x.dtsi` 的 `rknpu_mmu` 挂 `power-domains = <RK3568_PD_NPU>`，IOMMU（`drivers/iommu`）probe 早于 PMIC（`drivers/mfd`），而 NPU 电源轨不在 PMIC 硬件上电时序内 → 内核开 NPU 电源域时无电，NIU 不回 idle ack，BSP `pm_domains.c` 直接 `panic_on_set_idle`（`failed to get ack on domain 'npu' ... val=0x6`）。内核侧救不了（`npu-supply` 遇 `-EPROBE_DEFER` 被静默跳过）。RK3588/RK3576 的 `rknpu_mmu` 不挂电源域、由 rknpu 驱动先 `regulator_enable` 再开域，故无此问题。flange 通用 `rk3568_defconfig` 的 U-Boot DT（`rk3568-evb`）无 PMIC、extlinux 下也读不到内核 DTB，因此各 RK356x 板用 bootloader patch `0001-uboot-dts-enable-vdd-*` 在 U-Boot DTS 里声明 NPU 供电那一路 DCDC（RK809 方案 DCDC4 `vdd_npu`；RK817 方案 GPU/NPU 共用 DCDC2 `vdd_gpu`，**DCDC4 是 3.3V，切勿套 RK809 版**），SoC 层 `bootloader.config` 同时把 `interrupt-parent` 移出 `CONFIG_OF_SPL_REMOVE_PROPS`（否则 U-Boot rk8xx probe 失败）。U-Boot 串口应见 `PMIC:  RK8xx` 与 `<name> init 900000 uV`。早期 3 块板曾以"NPU 物理不可用"禁用 NPU，属误判。实板验证见 [orangepi-cm4](../boards/orangepi-cm4.md)
- `rockchip-u-boot` 跟踪 `next-dev-v2026.01` 分支 HEAD（未锁 commit），上游改动会让平台 patch 上下文失配、全 rockchip 板 bootloader 阶段同时报 `Hunk FAILED`。遇到此类失败先查上游该文件的近期提交，不要靠删缓存重试
- **OP-TEE 全平台打包**：上游 `rk35xx` defconfig 都启用 `CONFIG_OPTEE_CLIENT`（u-boot 开机强制查 OP-TEE）。平台 patch `0006-rockchip-fit-uncomment-bl32-node.patch` 取消注释 FIT 生成器 `make_fit_atf.sh` 的 `gen_bl32_node`，把 rkbin BL32（tee.bin）打进 u-boot.itb，SPL 加载交 BL31、client 检查通过正常启动。arm64 下**不可**启 `CONFIG_SPL_OPTEE`（会拉 armv7 专用 `spl_optee.S` 编不过；`fit_args.sh` 令 ARCH=arm64 时 `gen_bl32_node` 自动跳过该门槛）。启用 OP-TEE client 的引导链必须有匹配的 BL32
