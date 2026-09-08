"""UNO Q 的 Ubuntu、独立用户数据和与内核匹配的 EFI 输入。"""

import math
import hashlib
import json
from pathlib import Path

from builder.chroot import ChrootContext
from builder.docker import BuildError
from builder.rootfs import RootfsBuilder


USERDATA_UUID = "66f6d9a8-6ce3-46f6-b679-a1a1d991ba19"


def kernel_release(rootfs_dir: Path) -> str:
    """拒绝多版本或缺失模块，避免生成和 Image 不匹配的 initrd。"""
    modules = rootfs_dir / "lib/modules"
    releases = sorted(p.name for p in modules.iterdir() if p.is_dir()) if modules.is_dir() else []
    if len(releases) != 1:
        raise BuildError(f"UNO Q 必须恰有一个内核模块版本，实际为 {releases}")
    return releases[0]


class Qrb2210RootfsBuilder(RootfsBuilder):
    """复用两阶段 rootfs；所有活树操作仍在原生 staging 内执行。"""

    FSTAB_MOUNTS = (
        ("LABEL=rootfs", "/", "ext4"),
        (f"UUID={USERDATA_UUID}", "/home/arduino", "ext4"),
    )

    def _post_customize(self, rootfs_dir: Path, config: dict) -> None:
        if config.get("rootfs", {}).get("default_user") != "arduino":
            raise BuildError("UNO Q 运行时要求 arduino 为 UID 1000 默认用户")
        release = kernel_release(rootfs_dir)
        image = self._target_dir() / "kernel/Image"
        if not image.is_file():
            raise BuildError(f"缺少 initramfs 对应内核：{image}")
        boot = rootfs_dir / "boot"
        boot.mkdir(exist_ok=True)
        self.docker.run_privileged(["cp", str(image), str(boot / f"vmlinuz-{release}")])
        kernel_config = self._target_dir() / "kernel/config"
        if not kernel_config.is_file():
            raise BuildError(f"缺少 initramfs 压缩能力配置：{kernel_config}")
        if "CONFIG_ATH10K_SNOC=m" not in kernel_config.read_text().splitlines():
            raise BuildError("UNO Q 校准要求 ATH10K_SNOC=m，在切根后才加载无线驱动")
        self.docker.run_privileged(["cp", str(kernel_config), str(boot / f"config-{release}")])
        self.docker.run_privileged(["chown", "-R", "1000:1000", str(rootfs_dir / "home/arduino")])
        self._initrd = self._work_dir / "initrd.img"
        self._efi = self._work_dir / "bootaa64.efi"
        with ChrootContext(rootfs_dir, self.docker) as chroot:
            chroot.run(["ldconfig"])
            chroot.run(["/usr/lib/flange/unoq/verify-runtime", "--build"],
                       label="核验 UNO Q 固件、工具链和 Ubuntu ABI")
            chroot.run(["/usr/lib/flange/unoq/verify-usb"], label="核验 patched adbd Ubuntu ABI")
            chroot.run(["depmod", "-a", release])
            chroot.run(["update-initramfs", "-c", "-k", release])
            listing = self.docker.run_privileged(
                ["chroot", str(rootfs_dir), "lsinitramfs", f"/boot/initrd.img-{release}"],
                capture=True,
            ).stdout
            if "scripts/local-bottom/unoq-bdf" not in listing or "ath10k_snoc.ko" in listing:
                raise BuildError("initrd 缺少 BDF 选择脚本或仍提前携带 ath10k_snoc")
            if not any((rootfs_dir / "lib/modules" / release).rglob("ath10k_snoc.ko*")):
                raise BuildError("rootfs 缺少切根后需要的 ath10k_snoc 模块")
            report = rootfs_dir / "usr/share/flange/unoq/initramfs-report.json"
            report.write_text(json.dumps({
                "kernel_release": release, "bdf_script": True,
                "early_ath10k_snoc": False, "rootfs_ath10k_snoc": True,
                "listing_sha256": hashlib.sha256(listing.encode()).hexdigest(),
            }, indent=2) + "\n")
            chroot.run(["systemctl", "enable", "arduino-router.service",
                        "arduino-app-cli.service", "flange-unoq-data.service",
                        "flange-unoq-grow-userdata.service",
                        "rmtfs.service", "tqftpserv.service", "qbootctl.service", "adbd.service",
                        "flange-unoq-audio.service", "arduino-avahi-serial.service",
                        "arduino-cloud-connector.service", "arduino-router-serial.path"])
        self.docker.run_privileged(["chown", "-R", "1000:1000", str(rootfs_dir / "home/arduino")])
        initrd = boot / f"initrd.img-{release}"
        efi = rootfs_dir / "usr/lib/systemd/boot/efi/systemd-bootaa64.efi"
        for source, destination in ((initrd, self._initrd), (efi, self._efi)):
            if not source.is_file() or not source.stat().st_size:
                raise BuildError(f"UNO Q 必需启动资源缺失：{source}")
            self.docker.run_privileged(["cp", str(source), str(destination)])

    def _build_image(self, rootfs_dir: Path, config: dict) -> None:
        home = rootfs_dir / "home/arduino"
        if not home.is_dir():
            raise BuildError("UNO Q userdata 缺少 arduino 用户目录")
        used = int(self.docker.run(["du", "-sm", str(home)], capture=True).stdout.split()[0])
        size_mb = max(1024, math.ceil((used * 1.15 + 64) / 256) * 256)
        budget = self._partition_size_mb(config, "userdata")
        if size_mb > budget:
            raise BuildError(f"UNO Q userdata 需要 {size_mb} MiB，预算仅 {budget} MiB")
        size_mb = budget
        self._userdata = self._work_dir / "userdata.img"
        self.docker.run(["truncate", "-s", f"{size_mb}M", str(self._userdata)])
        self.docker.run(["mke2fs", "-t", "ext4", "-L", "userdata", "-U", USERDATA_UUID,
                         "-E", "root_owner=1000:1000", "-F", "-q", "-d", str(home), str(self._userdata)])
        # 清空的是本次 staging 的副本，userdata 镜像已完整生成。
        self.docker.run_privileged(["find", str(home), "-mindepth", "1", "-delete"])
        super()._build_image(rootfs_dir, config)

    def collect(self, src_dir: Path, config: dict) -> dict:
        return {**super().collect(src_dir, config), "initrd": self._initrd,
                "userdata": self._userdata, "bootaa64": self._efi}
