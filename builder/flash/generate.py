"""flash-config.json 生成（**构建期**，在 Docker 内跑）。

从 FINAL_CONFIG 推导出"哪个镜像写到哪个偏移"，产物是 target 目录下的
`flash-config.json`。它是构建产物的一部分，改这里必须让 image 组件失效，
所以本模块**进**构建逻辑指纹 —— 与宿主机侧的 strategy/execute 相反。
"""

import hashlib
from pathlib import Path

from builder.flash.model import (
    FlashConfig,
    FlashError,
    FlashIdentityConfig,
    FlashPartition,
    _atomic_write_text,
)
from builder.flash.plan import get_flash_plan
from builder.partition.layout import PartitionLayout
from builder.flash.spi import SPI_IMG_ALIGN, SPI_NOR_SIZE, build_spi_image
from builder.partition.rockchip import (
    generate_parameter_txt,
    parse_parameter_text,
    validate_parameter_capacity,
)
from builder.partition.size import parse_size
from builder.paths import PROJECT_ROOT


# ---------------------------------------------------------------------------
# 配置生成器（构建时使用）
# ---------------------------------------------------------------------------


class FlashConfigGenerator:
    """从 FINAL_CONFIG 生成 flash-config.json。"""

    def generate(self, config: dict, target_dir: Path, *, context=None, source=None) -> Path:
        """生成 flash-config.json 到 target_dir，返回文件路径。

        ``protected`` 标记规则：``type == "raw"`` 一律 True；启用 recovery 时
        ``recovery.protected_partitions`` 名单中的分区也置 True；recovery 自身
        分区始终视为受保护（设备端不允许从 recovery 内重写自己）。
        """
        platform = config.get("platform", "")
        plan = get_flash_plan(platform)
        image_map = plan.partition_image_map(config)

        recovery_cfg = config.get("recovery") or {}
        protected_set: set[str] = set(recovery_cfg.get("protected_partitions") or [])
        if recovery_cfg.get("enabled", False):
            protected_set.add("recovery")

        partition_cfg = config.get("partitions", {}) or {}
        partition_format = partition_cfg.get("format", "gpt")
        partitions: list[FlashPartition] = []
        parameter_relative = ""
        parameter_text = ""
        parameter_entries = []
        parameter_sha256 = ""
        rootfs_mtd_index = None
        storage_cfg = config.get("storage") or {}
        storage_size = storage_cfg.get("size", "")
        storage_type = storage_cfg.get("type", "")
        needs_parameter = platform == "rockchip" and (
            partition_format == "mtd"
            or bool(config.get("flash_storage"))
            or storage_type == "spinand"
        )

        if needs_parameter:
            try:
                if partition_format == "mtd":
                    parameter_source = Path(partition_cfg.get("parameter", ""))
                    if not parameter_source.is_absolute():
                        parameter_source = (
                            context.tool_root if context else PROJECT_ROOT
                        ) / parameter_source
                    parameter_text = parameter_source.read_text(encoding="utf-8")
                else:
                    machine = (config.get("rkbin") or {}).get("mkimage_chip", "RK3576").upper()
                    parameter_text = generate_parameter_txt(
                        partition_cfg.get("entries") or [],
                        machine=machine,
                    )
                parameter_entries = parse_parameter_text(parameter_text)
                total_bytes = parse_size(storage_size).bytes
                validate_parameter_capacity(parameter_entries, total_bytes)
            except (OSError, TypeError, ValueError) as exc:
                raise FlashError(f"无法生成 Rockchip parameter/flash-config: {exc}") from exc
            parameter_relative = "parameter.txt"
            parameter_sha256 = hashlib.sha256(parameter_text.encode("utf-8")).hexdigest()
            rootfs_mtd_index = next(
                (index for index, entry in enumerate(parameter_entries) if entry.name == "rootfs"),
                None,
            )

        configured_types = {
            entry.get("name"): entry.get("type", "raw")
            for entry in partition_cfg.get("entries") or []
        }
        if parameter_entries:
            # parameter 是实际由 upgrade_tool 消费的布局事实源；flash config
            # 必须从同一解析结果派生，避免单位或 size 表达方式漂移。
            for entry in parameter_entries:
                if storage_type == "spinand" and entry.name == "idbloader":
                    continue
                image = image_map.get(entry.name, "")
                if not image:
                    continue
                ptype = configured_types.get(entry.name, "raw")
                if (
                    entry.name == "rootfs"
                    and (config.get("rootfs") or {}).get("image_format") == "ubi"
                ):
                    ptype = "ubi"
                partitions.append(
                    FlashPartition(
                        name=entry.name,
                        offset=f"0x{entry.offset:x}",
                        type=ptype,
                        image=image,
                        protected=bool(ptype == "raw" or entry.name in protected_set),
                        size="remaining" if entry.size is None else f"0x{entry.size:x}",
                    )
                )
        else:
            # GPT 路径：几何走 PartitionLayout —— 与 image.py 写进 raw.img 的
            # GPT 是同一份解析结果。
            #
            # 此前这里把 config 里的字符串原样抄进 flash-config.json：声明
            # `size: "remaining"` + `image_size: "2G"` 时，GPT 里是 2G 而
            # flash-config 里写着 "remaining"，两侧对不上；声明 `size: "4M"`
            # 时刷写侧的 int(part.size, 0) 直接 ValueError。
            for part in PartitionLayout.from_config(config):
                image = image_map.get(part.name, "")
                if not image:
                    continue
                ptype = part.type or "raw"
                if (
                    part.name == "rootfs"
                    and (config.get("rootfs") or {}).get("image_format") == "ubi"
                ):
                    ptype = "ubi"
                partitions.append(
                    FlashPartition(
                        name=part.name,
                        offset=f"0x{part.offset_sectors:x}",
                        type=ptype,
                        image=image,
                        protected=bool(ptype == "raw" or part.name in protected_set),
                        size=f"0x{part.size_sectors:x}",
                    )
                )

        # 构造 pre_flash（由平台策略声明）
        pre_flash = plan.generate_pre_flash_config(config)

        flash_config = FlashConfig(
            platform=platform,
            flash_tool=config.get("flash_tool", ""),
            board=config["board"],
            product=config.get("product", "default"),
            variant=config.get("variant", "release"),
            soc=config.get("soc", ""),
            sector_size=int(config.get("partitions", {}).get("sector_size", 512)),
            storage=config.get("flash_storage", ""),
            storage_type=storage_type,
            partition_format=partition_format,
            parameter=parameter_relative,
            storage_size=storage_size,
            rootfs_mtd_index=rootfs_mtd_index,
            parameter_sha256=parameter_sha256,
            partitions=partitions,
            pre_flash=pre_flash,
            identity=FlashIdentityConfig(
                chip_patterns=list((config.get("flash_identity") or {}).get("chip_patterns") or []),
                storage_patterns=list(
                    (config.get("flash_identity") or {}).get("storage_patterns") or []
                ),
                require_rid=bool((config.get("flash_identity") or {}).get("require_rid", False)),
            ),
        )

        # SPI 启动固件 spi.img → `flange flash --spi-firmware` 写入 SPI NOR。两条路:
        #  (a) prebuilt_spi_image：直接用 radxa bsp 预编的整体 spi.img（RK3576 ROCK
        #      4D —— RK3576 idbloader 须 boot_merger 装配含 rk3576_boost，flange 通用
        #      mkimage rksd 路径缺 boost → SPL 环境不全、u-boot 读 UFS 崩；详见 design）。
        #  (b) flash_spi_loader：flange 自编 idbloader+u-boot.itb 合成（eMMC/SD 板）。
        prebuilt = config.get("bootloader", {}).get("prebuilt_spi_image")
        spi_out = target_dir / "bootloader" / "spi.img"
        if prebuilt and config.get("platform") == "rockchip":
            # prebuilt_spi_image = {url, sha256}：从 radxa 官方下载（不入库 16MB
            # blob），ensure_prebuilt_image 原子下载 + sha256 校验、缓存到
            # .build/sources/prebuilt（幂等，缓存命中无网亦可）。
            from builder.source import SourceManager

            if source is None and context is None:
                raise ValueError("预编 SPI 固件下载必须提供 WorkspaceContext 或 SourceManager")
            src = source or SourceManager(context=context)
            img_path = src.ensure_prebuilt_image(config.get("board", "prebuilt"), prebuilt)
            spi_out.parent.mkdir(parents=True, exist_ok=True)
            data = img_path.read_bytes()
            # SPINOR 实际可写略少于 16MB 标称（末端 GPT backup ~33 扇区不可写）；官方
            # 预编 spi.img 填满 16MB 会触发 upgrade_tool "partition too small"，截到可
            # 写上限内即可——idbloader/u-boot.itb/primary GPT 都在头部保留，BootROM 按
            # 固定偏移找 idbloader 不依赖 GPT（flange 自编 spi.img 本就无 GPT 也能启动）。
            cap = SPI_NOR_SIZE - SPI_IMG_ALIGN
            spi_out.write_bytes(data[:cap] if len(data) > cap else data)
        elif config.get("flash_spi_loader") and config.get("platform") == "rockchip":
            build_spi_image(target_dir / "bootloader", spi_out)

        # 发布顺序刻意为 parameter → flash config。中断发生在两者之间时，旧清单
        # 的摘要会与新 parameter 不符，preflight 必然失败；反向顺序会放行旧布局。
        if needs_parameter:
            _atomic_write_text(target_dir / "parameter.txt", parameter_text)
        output = target_dir / "flash-config.json"
        flash_config.to_json(output)
        return output
