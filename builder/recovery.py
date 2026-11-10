"""RecoveryBuilder — recovery 镜像构建器。

recovery 是一个独立的 ext4 文件系统镜像（label=recovery），构建流程与 normal
rootfs **完全同形**：base 快照 → customize → fstab → 成像。因此它继承
`RootfsBuilder`，只声明自己偏离的部分：

  - 读 `config["recovery"]` 子树（packages / custom_packages / …），
    与 normal rootfs 的包集合互不影响，两者共用同一份 ubuntu-base tarball
  - overlay 走 `recovery-overlay` 目录，同一块板可以给救援系统不同的配置
  - Phase 2 只做 deb + 内核模块 + overlay：recovery 仅通过 adb 通道交互，
    账号体系、locale、Wi-Fi 固件都没有意义
  - deb 按 `recovery.custom_packages` 挑选而不是全装 —— 它是几十 MB 的救援
    系统，装不下也不需要全部 App
  - 额外写 `/etc/flange/recovery-config.json`（分区表与刷写策略的事实源）

此前这些"偏离"是靠**整段抄一份编排**表达的：13 个方法与基类同名，逐方法对比
后 10 个只差参数名与 status 文案，剩下 3 个是抄件漂移 —— 硬编码
`qemu-aarch64-static`（armhf 板会拿错 emulator）、`_partition_size_mb` 忽略
`image_size`、以及缺容量门禁。合并之后这类漂移不再可能发生。
"""

from __future__ import annotations

import json
from pathlib import Path

from builder.rootfs import RootfsBuilder


# 设备端读取该路径冻结分区表与刷写策略。
RECOVERY_CONFIG_PATH = "etc/flange/recovery-config.json"

# 文件系统 label 与 fstab 中的 LABEL= 一致。
FS_LABEL = "recovery"


def build_recovery_config(config: dict) -> dict:
    """生成 ``/etc/flange/recovery-config.json`` 的内容字典。

    设备端 ``recoveryctl`` 与宿主机 ``flange recovery`` 都把该文件视作分区表
    和刷写策略的事实源；保持纯函数以便单测覆盖。

    schema（v1）::

        {
          "version": 1,
          "board": "...", "product": "...", "variant": "...",
          "transport": "adb",
          "partitions": [
            {
              "name": "rootfs",
              "offset": "0x40000",
              "size": "0x200000",
              "type": "ext4",
              "protected": false
            },
            ...
          ]
        }

    ``protected`` 规则：``type == "raw"`` 一律视为受保护；此外若分区名出现在
    ``recovery.protected_partitions`` 列表中也标记为受保护。recovery 自身
    分区始终保护（设备端不允许从 recovery 内重写自己）。
    """
    recovery_cfg = config.get("recovery") or {}
    protected_set = {*(recovery_cfg.get("protected_partitions") or []), "recovery"}
    transport = recovery_cfg.get("transport", "adb")

    partitions_out: list[dict] = []
    for entry in (config.get("partitions") or {}).get("entries") or []:
        is_raw = entry.get("type") == "raw"
        protected = bool(is_raw or entry.get("name") in protected_set)
        partitions_out.append(
            {
                "name": entry["name"],
                "offset": entry.get("offset", ""),
                "size": entry.get("size", ""),
                "type": entry.get("type", ""),
                "protected": protected,
            }
        )

    return {
        "version": 1,
        "board": config.get("board", ""),
        "product": config.get("product", "default"),
        "variant": config.get("variant", "release"),
        "transport": transport,
        "partitions": partitions_out,
    }


class RecoveryBuilder(RootfsBuilder):
    """recovery 组件构建器基类。"""

    component = "recovery"

    #: 文件系统中存放 recovery-config.json 的相对路径（不含前导斜杠）。
    config_rel_path = RECOVERY_CONFIG_PATH

    #: 文件系统 label。与 `component` 同值，保留符号供既有调用方引用。
    fs_label = FS_LABEL

    #: recovery 不挂载 normal rootfs 或 userdata；需要时由 recoveryctl 显式
    #: 挂到独立目录，避免误触 normal 系统的运行时状态。
    FSTAB_MOUNTS = (
        (f"LABEL={FS_LABEL}", "/", "ext4"),
        ("LABEL=boot", "/boot", "ext4"),
    )

    #: 平台/板级 overlay 走独立目录，与 normal rootfs 的 overlay 分开：
    #: components/platform/<p>/recovery-overlay/、components/board/<b>/…
    OVERLAY_SUBDIR = "recovery-overlay"

    def _build_phase2(self, recovery_dir: Path, config: dict) -> None:
        """deb + 内核模块 + overlay。

        与 normal rootfs 不同，recovery 不配置账号（不建普通用户、不写
        sudoers.d、不锁 root）、不装 locale、不装 extra_firmware：它只通过
        adb 通道交互运行，这些都没有意义，且每一项都要占救援分区的空间。
        """
        from builder.distro import get_distro
        distro = get_distro(config, self.context)
        distro.install_apps(self, recovery_dir, config)
        self._install_kernel_modules(recovery_dir, config)
        self.apply_overlays(recovery_dir, config)
        distro.export_packages(self, recovery_dir)

    def _post_customize(self, recovery_dir: Path, config: dict) -> None:
        """写入设备端读取的分区表/刷写策略事实源。"""
        target = recovery_dir / self.config_rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(build_recovery_config(config), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
