"""RootfsBuilder — 各平台 rootfs 构建器的公共基类。

通用能力（与平台无关）：
  - apply_overlays：platform overlay → board overlay 两层覆盖
  - extra_firmware：从外部仓库拉取固件文件并写入 rootfs
"""

import shutil
from pathlib import Path
from builder.base import ComponentBuilder


class RootfsBuilder(ComponentBuilder):
    """rootfs 构建器基类。

    各平台子类继承此类，获得通用 rootfs 能力，再叠加平台特定逻辑。
    """

    def apply_overlays(self, rootfs_dir: Path, config: dict):
        """按优先级顺序应用 overlay 文件：rootfs → platform → board。

        优先级从低到高，后应用的同名文件覆盖先应用的：
          components/rootfs/overlay/          与 OS/发行版绑定，所有平台共用
          components/platform/<p>/overlay/    与芯片平台绑定
          components/board/<b>/overlay/       与具体板子绑定
        """
        for overlay_dir, label in [
            (Path("components/rootfs/overlay"),                          "rootfs"),
            (Path(f"components/platform/{config['platform']}/overlay"),  "platform"),
            (Path(f"components/board/{config['board']}/overlay"),        "board"),
        ]:
            if overlay_dir.exists() and any(overlay_dir.iterdir()):
                self._status(f"复制 {label} overlay 文件...")
                self.docker.run_privileged(
                    ["cp", "-a", f"{overlay_dir}/.", str(rootfs_dir)])

    def _install_extra_firmware(self, rootfs_dir: Path, config: dict):
        """安装额外固件文件到 rootfs。

        config["rootfs"]["extra_firmware"] 格式：
          [
            {
              "name": "radxa",
              "repo": "https://github.com/radxa-pkg/radxa-firmware",
              "branch": "main",
              "repo_subdir": "radxa-firmware/lib/firmware",  # 可选，仓库内子目录作为 files 的根
              "files": ["brcm/brcmfmac43430-sdio.txt", ...],
              "dest": "lib/firmware",   # 相对 rootfs 根目录，默认 lib/firmware
            }
          ]

        files 中每条路径相对于仓库根目录（或 repo_subdir 指定的子目录），复制时保留目录结构。
        例：repo_subdir="radxa-firmware/lib/firmware", files=["brcm/foo.txt"], dest="lib/firmware"
            → rootfs/lib/firmware/brcm/foo.txt
        """
        extra_firmware = config.get("rootfs", {}).get("extra_firmware", [])
        if not extra_firmware:
            return
        for fw in extra_firmware:
            name = fw["name"]
            self._status(f"同步固件仓库: {name}")
            fw_dir = self.source.ensure_extra_firmware(name, fw)
            repo_subdir = fw.get("repo_subdir", "")
            fw_base = fw_dir / repo_subdir if repo_subdir else fw_dir
            dest_base = rootfs_dir / fw.get("dest", "lib/firmware")
            for rel_path in fw.get("files", []):
                src = fw_base / rel_path
                if not src.exists():
                    raise FileNotFoundError(
                        f"固件文件不存在: {src}（仓库: {name}）")
                dest = dest_base / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
            self._status(f"已安装 {len(fw.get('files', []))} 个固件文件 ({name})")
