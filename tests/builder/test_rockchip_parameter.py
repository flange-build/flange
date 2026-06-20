"""Rockchip parameter.txt（GPT 分区表）生成测试。

UFS 刷写走 `upgrade_tool di -p parameter.txt`，由 loader 按 parameter 在 4K
UFS 上落盘。parameter 的 offset/size 沿用 flange 的 512B 扇区单位（hex），
loader 自行映射到 4K。
"""

from __future__ import annotations

from builder.flash import generate_parameter_txt

ENTRIES = [
    {"name": "idbloader", "offset": "0x40", "size": "0x2000", "type": "raw"},
    {"name": "uboot", "offset": "0x4000", "size": "0x2000", "type": "raw"},
    {"name": "boot", "offset": "0x8000", "size": "0x20000", "type": "ext4"},
    {"name": "recovery", "offset": "0x28000", "size": "0x100000", "type": "ext4"},
    {"name": "rootfs", "offset": "0x128000", "size": "remaining",
     "type": "ext4", "image_size": "2G", "grow_on_first_boot": True},
]


class TestParameterCmdline:
    def test_segments_size_at_offset_name(self):
        p = generate_parameter_txt(ENTRIES, machine="RK3576")
        assert "0x00002000@0x00000040(idbloader)" in p
        assert "0x00002000@0x00004000(uboot)" in p
        assert "0x00020000@0x00008000(boot:bootable)" in p
        assert "0x00100000@0x00028000(recovery)" in p

    def test_rootfs_uses_image_size_not_dash(self):
        # 该 loader 的 di -p 把 "-"(remaining) 算成 size=0 → "partition too
        # small"。rootfs 用 image_size(2G=0x400000 扇区)显式大小，grow 首启撑满。
        p = generate_parameter_txt(ENTRIES, machine="RK3576")
        assert "0x00400000@0x00128000(rootfs)" in p
        assert "-@" not in p  # 不再出现 remaining

    def test_gpt_type_and_rootfs_partuuid(self):
        p = generate_parameter_txt(ENTRIES, machine="RK3576")
        assert "TYPE: GPT" in p
        # 保留固定 PARTUUID，供 kernel cmdline root=PARTUUID 引用
        assert "uuid:rootfs=614e0000-0000-4000-8000-000000000000" in p

    def test_mtdparts_prefix(self):
        p = generate_parameter_txt(ENTRIES, machine="RK3576")
        assert "CMDLINE:" in p and "mtdparts=" in p
