"""刷写计划 —— 由配置推导"哪个镜像写到哪个偏移"（**构建期**）。

**为什么单独一层**：这两个方法（`partition_image_map` /
`generate_pre_flash_config`）此前长在宿主机刷写策略类上，但它们是纯粹的
config → 数据推导，产物 `flash-config.json` 进 image 组件的构建产物。

结果是构建期逻辑与 rkdeveloptool/qdl 的调用挤在同一个模块里，缓存只能整
文件排除 —— 改 flash-config 的生成规则不会让 image 失效（漏失效），而改
一句刷写命令行却会让整棵树重编（过失效）。

拆出来之后：本模块**进**构建逻辑指纹，`strategy` / `execute` 不进。
宿主机策略类继承对应的 Plan，既有的
`get_flash_strategy(p).partition_image_map(cfg)` 调用照旧可用。
"""

from abc import ABC, abstractmethod

from builder.flash.model import PreFlashConfig


class FlashPlan(ABC):
    """各平台刷写计划的公共契约。"""

    @abstractmethod
    def partition_image_map(self, config: dict) -> dict[str, str]:
        """返回 {分区名: 镜像相对路径} 映射。"""

    def generate_pre_flash_config(self, config: dict) -> PreFlashConfig:
        """生成平台特定的 pre_flash 配置。默认返回空配置。"""
        return PreFlashConfig()


class RockchipFlashPlan(FlashPlan):
    """Rockchip：idbloader + u-boot.itb + 逐分区镜像。"""

    def partition_image_map(self, config: dict) -> dict[str, str]:
        m = {
            "idbloader": "bootloader/idbloader.img",
            "uboot": "bootloader/u-boot.itb",
            "boot": "boot/boot.img",
            "rootfs": (
                "rootfs/rootfs.ubi"
                if (config.get("rootfs") or {}).get("image_format") == "ubi"
                else "rootfs/rootfs.img"
            ),
        }
        if (config.get("recovery") or {}).get("enabled", False):
            m["recovery"] = "recovery/recovery.img"
        # amp 协处理器固件：启用时纳入刷写映射，使 flash-config.json 含 amp、
        # `flange flash amp` 可单刷（仿 recovery 的 enabled gate）。
        if (config.get("amp") or {}).get("enabled", False):
            m["amp"] = "amp/amp.img"
        return m

    def generate_pre_flash_config(self, config: dict) -> PreFlashConfig:
        return PreFlashConfig(download_boot="bootloader/miniloader.bin")


class AllwinnerA733FlashPlan(FlashPlan):
    """Allwinner A733：SD 卡模式整体 dd raw.img。"""

    def partition_image_map(self, config: dict) -> dict[str, str]:
        # SD 卡模式整体 dd raw.img；列出 recovery 仅为生成 flash-config.json 时
        # 携带 protection 元数据，write_partition 不会被逐分区调用。
        m = {
            "boot0": "bootloader/boot0_sdcard.bin",
            "boot0_ufs": "bootloader/boot0_ufs.bin",
            "boot_package": "bootloader/boot_package.fex",
            "boot": "boot/boot.img",
            "rootfs": "rootfs/rootfs.img",
        }
        if (config.get("recovery") or {}).get("enabled", False):
            m["recovery"] = "recovery/recovery.img"
        return m


class AmlogicFlashPlan(FlashPlan):
    """Amlogic：FIP 封装的启动镜像 + fastboot 逐分区。"""

    # MaskROM 的 USB VID/PID：既写进 flash-config.json（构建产物），也用于
    # 宿主机侧的设备检测。定义在 Plan 上，宿主机策略继承同一份 —— 分成两处
    # 各写一遍，就是"刷写工具找不到设备"这类问题的来源。
    MASKROM_VID = "1b8e"
    MASKROM_PID = "c003"

    def partition_image_map(self, config: dict) -> dict[str, str]:
        """amlogic 平台分区 → 镜像路径映射。

        ``bootloader`` 指向 FIP 封装的 SD/eMMC 启动镜像
        （``u-boot.bin.sd.bin``），由 fastboot 写入 eMMC hw boot0 分区
        （由 u-boot 板级 ``CONFIG_FASTBOOT_FLASH_MMC_DEV`` 路由）。
        """
        m = {
            "bootloader": "bootloader/u-boot.bin.sd.bin",
            "boot": "boot/boot.img",
            "rootfs": "rootfs/rootfs.img",
        }
        if (config.get("recovery") or {}).get("enabled", False):
            m["recovery"] = "recovery/recovery.img"
        return m

    def generate_pre_flash_config(self, config: dict) -> PreFlashConfig:
        """生成 amlogic 平台的 pre_flash 配置。

        - ``download_boot`` 指向**裸 FIP**（``u-boot.bin``，build-fip.sh 直接
          产出）而非 SD 格式（``u-boot.bin.sd.bin``）。boot-g12.py 在
          SRAM 解第一个 64KB 后会通过 AMLC 控制传输请求剩余 chunks，需要
          binary 的 BL2 位于 offset 0；SD 格式前置了 block-1 header，BL2
          被推到错误偏移，BL2 起来后 AMLC 握手超时。
        - ``usb_vid`` / ``usb_pid``：amlogic MaskROM 通用 USB 描述符
          ``1b8e:c003``。
        """
        return PreFlashConfig(
            download_boot="bootloader/u-boot.bin",
            usb_vid=self.MASKROM_VID,
            usb_pid=self.MASKROM_PID,
        )


class QualcommFlashPlan(FlashPlan):
    """Qualcomm：整盘 raw.img 经 edl-ng 刷入。"""

    def partition_image_map(self, config: dict) -> dict[str, str]:
        # 整盘 raw.img 经 edl-ng write-sector 刷入；映射仅作 flash-config 元数据。
        return {"system": "image/raw.img"}




#: 平台 → 构建期刷写计划。宿主机策略类继承同名 Plan，两侧不会漂移。
_FLASH_PLANS: dict[str, type[FlashPlan]] = {
    "rockchip": RockchipFlashPlan,
    "allwinnera733": AllwinnerA733FlashPlan,
    "amlogic": AmlogicFlashPlan,
    "qualcommqcs6490": QualcommFlashPlan,
    "qualcommsc8280xp": QualcommFlashPlan,
}


def get_flash_plan(platform: str) -> FlashPlan:
    """取平台的构建期刷写计划。"""
    cls = _FLASH_PLANS.get(platform)
    if cls is None:
        raise KeyError(
            f"不支持的平台: {platform}（支持: {', '.join(_FLASH_PLANS)}）")
    return cls()
