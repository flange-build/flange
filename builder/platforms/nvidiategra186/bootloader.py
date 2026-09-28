"""NVIDIA Tegra186 bootloader 构建器 —— 收取 L4T BSP 预编译启动链。

MB1 / MB2 / cboot / BPMP / TOS / U-Boot 都是 NVIDIA 预编译件，flange 不编译：
下载并校验 L4T BSP 包，按 flash.sh 的 cp2local 规则把 ``bootloader/`` 顶层文件与
配置点名的子目录文件平铺成 tegraflash 刷写目录，再复现 flash.sh 在刷写时生成的
两个文件：装载 U-Boot 的 Android boot image（``kernel`` 分区）与
``kernel_bootctrl.bin``。cboot 使用的 DTB 也来自 BSP，不随 flange 内核 DTS 变化。
"""

import os
import re
import shutil
import tarfile
from pathlib import Path, PurePosixPath

from builder.base import ComponentBuilder

BSP_ROOT = "Linux_for_Tegra"
# flash.sh 生成 emmc_bootblob_ver.txt 时读取的 BSP 版本号，image 组件同样需要。
BSP_VERSION_FILE = "nv_tegra/bsp_version"
UBOOT_IMAGE = "boot.img"
BOOTCTRL_FILE = "kernel_bootctrl.bin"
# flash.sh：给 OTA 生成索引用的 kernel 启动控制占位文件，20 字节全零。
BOOTCTRL_SIZE = 20


def extract_bsp(archive: Path, destination: Path, extra: list[str]) -> Path:
    """流式解包刷写所需的 BSP 成员，返回 BSP 根目录。

    只取 ``bootloader/`` 子树与 ``extra`` 点名的文件；tarfile 的 ``data``
    过滤器拒绝绝对路径、``..``、设备文件与指向目标树外的链接。
    """
    prefix = f"{BSP_ROOT}/bootloader/"
    wanted = {f"{BSP_ROOT}/{path}" for path in extra}
    try:
        with tarfile.open(archive, "r|*") as bsp:
            for member in bsp:
                if not (member.name.startswith(prefix) or member.name in wanted):
                    continue
                # data 过滤器只拦越出解包目录的路径；bootloader/../ 仍在目录内，
                # 但会让前缀筛选失去意义，显式拒绝。
                if ".." in PurePosixPath(member.name).parts:
                    raise ValueError(f"BSP 包含不安全的成员: {member.name}")
                bsp.extract(member, destination, filter="data")
    except tarfile.FilterError as error:
        raise ValueError(f"BSP 包含不安全的成员: {error}") from error
    root = destination / BSP_ROOT
    missing = [path for path in extra if not (root / path).is_file()]
    if missing:
        raise FileNotFoundError(f"BSP 中不存在配置引用的文件: {', '.join(missing)}")
    return root


def stage_flash_tree(bsp_root: Path, tree: Path, tegraflash: dict) -> None:
    """按 flash.sh 的平铺规则组装刷写目录，并确认 tegraflash 参数引用的文件都在。"""
    tree.mkdir(parents=True)
    for entry in sorted((bsp_root / "bootloader").iterdir()):
        target = tree / entry.name
        if entry.is_symlink():
            # 如 tos.img -> tos-trusty.img，已由解包过滤器确认不越出目录。
            target.symlink_to(os.readlink(entry))
        elif entry.is_file():
            shutil.copy2(entry, target)
    for relative in (
        *(tegraflash.get("extra_files") or []), tegraflash["layout_template"], BSP_VERSION_FILE,
    ):
        target = tree / PurePosixPath(relative).name
        if target.exists() or target.is_symlink():
            raise ValueError(f"{relative} 与刷写目录中已有文件同名: {target.name}")
        shutil.copy2(bsp_root / relative, target)

    referenced = [
        ("bl", tegraflash["bl"]),
        ("applet", tegraflash["applet"]),
        *((f"bct_configs.{name}", file) for name, file in tegraflash["bct_configs"].items()),
        *((f"bins.{entry['type']}", entry["file"]) for entry in tegraflash["bins"]),
    ]
    missing = [f"{field}={name}" for field, name in referenced if not (tree / name).is_file()]
    if missing:
        raise FileNotFoundError(
            "刷写目录缺少 bootloader.tegraflash 引用的文件: " + ", ".join(missing)
            + "；子目录中的文件请在 bootloader.tegraflash.extra_files 声明其 BSP 路径"
        )


def root_device(kernel_args: str) -> str:
    """flash.sh 把 rootfs 设备名写进 boot.img 头部的 board 字段。"""
    match = re.search(r"(?:^|\s)root=/dev/(\S+)", kernel_args)
    if not match:
        raise ValueError("boot.kernel_args 必须以 root=/dev/<设备> 指定 APP 分区")
    return match.group(1)


class Tegra186BootloaderBuilder(ComponentBuilder):
    component = "bootloader"

    def build(self, config: dict) -> dict:
        """启动链没有源码仓库，下载 BSP 后组装即可。"""
        self.compile(None, config)
        with self._step("收集产物"):
            return self.collect(None, config)

    def configure(self, src_dir, config: dict):
        pass

    def compile(self, src_dir, config: dict):
        bootloader = config["bootloader"]
        tegraflash = bootloader["tegraflash"]
        work = self.work_dir()
        with self._step("下载并解包 L4T BSP"):
            archive = self.source.ensure_prebuilt_image("l4t-bsp", bootloader["l4t_bsp"])
            bsp_root = extract_bsp(
                archive, work / "bsp",
                [*(tegraflash.get("extra_files") or []), tegraflash["uboot"], BSP_VERSION_FILE],
            )
        self._tree = work / "tegraflash"
        with self._step("组装 tegraflash 刷写目录"):
            stage_flash_tree(bsp_root, self._tree, tegraflash)
        kernel_args = config["boot"]["kernel_args"]
        with self._step("封装 U-Boot boot.img"):
            # 参数与 flash.sh 的 U-Boot 路径一致：无 ramdisk，cmdline 每段以空格结尾。
            # cboot 把头部 cmdline 拼进 ${cbootargs} 交给 U-Boot。
            self.docker.run(
                [
                    "./mkbootimg",
                    "--kernel", str(bsp_root / tegraflash["uboot"]),
                    "--ramdisk", "/dev/null",
                    "--board", root_device(kernel_args),
                    "--output", UBOOT_IMAGE,
                    "--cmdline", f"{kernel_args} ",
                ],
                cwd=str(self._tree),
                label="mkbootimg（U-Boot）",
            )
        (self._tree / BOOTCTRL_FILE).write_bytes(bytes(BOOTCTRL_SIZE))
        shutil.rmtree(work / "bsp")

    def collect(self, src_dir, config: dict) -> dict:
        return {"tegraflash": self._tree}
