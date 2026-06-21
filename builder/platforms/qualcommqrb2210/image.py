"""Qualcomm QRB2210 镜像组装策略 —— 按分区，不重建整盘 GPT。

UNO Q 的 bootloader 与 OS 共享同一块 eMMC 的固定 vendor GPT（约 67 分区），
flange 不重新分区、不组装 monolithic raw.img；本构建器仅生成 **flange
rawprogram**（qdl 格式），把 boot.img / rootfs.img 映射到 vendor GPT 既有的
boot / rootfs 槽位，供 QualcommQrb2210FlashStrategy 经
`qdl --allow-missing` 按分区刷写。

⚠️ rawprogram 的 start_sector / num_partition_sectors 取自 partitions 配置；
   该配置的 boot/rootfs offset/size 必须与 vendor GPT 既有槽位一致（取自
   armbian/qcombin 的 vendor rawprogram*.xml）。当前为占位值，实板 bring-up
   时校正（见 openspec tasks §4.4）。
"""

import tempfile
from pathlib import Path
from xml.sax.saxutils import quoteattr

from builder.base import ComponentBuilder
from builder.partition.size import resolve_image_size

# image 组件负责映射的分区 → 其镜像产物（相对 target_dir）。
PARTITION_IMAGES = {
    "boot":   "boot/boot.img",
    "rootfs": "rootfs/rootfs.img",
}


class Qrb2210ImageBuilder(ComponentBuilder):
    component = "image"

    def build(self, config: dict) -> dict:
        self.compile(None, config)
        return self.collect(None, config)

    def configure(self, src_dir, config: dict):
        pass

    def compile(self, src_dir, config: dict):
        self._work_dir = Path(tempfile.mkdtemp(prefix="flange-image-"))
        parts = config.get("partitions", {})
        sector = int(parts.get("sector_size", 512))
        entries = parts.get("entries", [])
        target_dir = self.cache.target_dir

        programs = []
        for entry in entries:
            name = entry["name"]
            image_rel = PARTITION_IMAGES.get(name)
            if not image_rel:
                continue  # 仅映射 boot / rootfs，其余 vendor 分区不在 flange rawprogram
            image_path = target_dir / image_rel
            label = entry.get("label", name)
            start_sector = int(entry.get("offset", "0"), 0)
            num_sectors = resolve_image_size(entry).sectors
            filename = Path(image_rel).name  # qdl 经 --include 搜索目录定位 basename
            if not image_path.exists():
                self._status(f"提示：{name} 镜像 {image_path} 暂不存在（构建后生成）")
            programs.append({
                "label": label,
                "filename": filename,
                "start_sector": start_sector,
                "num_sectors": num_sectors,
            })

        self._raw_program = self._work_dir / "flange_rawprogram.xml"
        self._raw_program.write_text(self._render_rawprogram(programs, sector))
        self._status(
            f"生成 flange rawprogram（{len(programs)} 分区，扇区 {sector}）："
            f"{', '.join(p['label'] for p in programs)}")

    def _render_rawprogram(self, programs: list[dict], sector: int) -> str:
        """渲染 qdl rawprogram XML（仅 boot/rootfs 两条目）。

        physical_partition_number=0（eMMC user 区）。start_sector 为 vendor GPT
        既有槽位起始扇区——务必与 vendor rawprogram 一致（见文件头 ⚠️）。
        """
        lines = ['<?xml version="1.0" ?>', "<data>"]
        for p in programs:
            attrs = (
                f'SECTOR_SIZE_IN_BYTES="{sector}" '
                f'file_sector_offset="0" '
                f'filename={quoteattr(p["filename"])} '
                f'label={quoteattr(p["label"])} '
                f'num_partition_sectors="{p["num_sectors"]}" '
                f'physical_partition_number="0" '
                f'start_sector="{p["start_sector"]}"'
            )
            lines.append(f"  <program {attrs} />")
        lines.append("</data>")
        return "\n".join(lines) + "\n"

    def collect(self, src_dir, config: dict) -> dict:
        return {"rawprogram": self._raw_program}
