"""RootfsBuilder — 各平台 rootfs 构建器的公共基类。

通用能力（与平台无关）：
  - extra_firmware：从外部仓库拉取固件文件并写入 rootfs
"""

import shutil
from pathlib import Path
from builder.base import ComponentBuilder


class RootfsBuilder(ComponentBuilder):
    """rootfs 构建器基类。

    各平台子类继承此类，获得通用 rootfs 能力，再叠加平台特定逻辑。
    """

    def _install_extra_firmware(self, rootfs_dir: Path, config: dict):
        """安装额外固件文件到 rootfs。

        config["rootfs"]["extra_firmware"] 格式：
          [
            {
              "name": "armbian",
              "repo": "https://github.com/armbian/firmware",
              "branch": "master",
              "files": ["brcm/brcmfmac43430-sdio.bin", ...],
              "dest": "lib/firmware",   # 相对 rootfs 根目录，默认 lib/firmware
            }
          ]

        files 中每条路径相对于仓库根目录，复制时保留目录结构。
        例：files=["brcm/foo.bin"], dest="lib/firmware"
            → rootfs/lib/firmware/brcm/foo.bin
        """
        extra_firmware = config.get("rootfs", {}).get("extra_firmware", [])
        if not extra_firmware:
            return
        for fw in extra_firmware:
            name = fw["name"]
            self._status(f"同步固件仓库: {name}")
            fw_dir = self.source.ensure_extra_firmware(name, fw)
            dest_base = rootfs_dir / fw.get("dest", "lib/firmware")
            for rel_path in fw.get("files", []):
                src = fw_dir / rel_path
                if not src.exists():
                    raise FileNotFoundError(
                        f"固件文件不存在: {src}（仓库: {name}）")
                dest = dest_base / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
            self._status(f"已安装 {len(fw.get('files', []))} 个固件文件 ({name})")
