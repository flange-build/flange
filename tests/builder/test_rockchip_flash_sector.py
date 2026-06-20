"""Rockchip 刷写策略扇区参数化测试。

覆盖 rockchip-platform spec "Rockchip 刷写策略按 sector_size 参数化 GPT 写入"
requirement —— 默认 512 的 GPT 截取与旧 33 扇区行为一致；4096 时按 4K 计算。
"""

from __future__ import annotations

from builder.flash import RockchipFlashStrategy, FlashConfig


class TestGptSlice:
    """`_gpt_slice` 返回 (从 raw.img 截取 GPT 的起始字节, 截取长度字节)。
    primary GPT 自 LBA1 起 = 1 个扇区的 header + 16KiB entries array。"""

    def test_512_matches_legacy_33_sectors(self):
        s = RockchipFlashStrategy()
        seek, length = s._gpt_slice(512)
        assert seek == 512
        # 旧实现写死 GPT_ENTRIES_SECTORS=33 → 33×512=16896，须保持 byte 一致
        assert length == 33 * 512

    def test_4096(self):
        s = RockchipFlashStrategy()
        seek, length = s._gpt_slice(4096)
        assert seek == 4096
        # header 扇区(4096) + 16KiB 标准 entries array
        assert length == 4096 + 16384


class TestGptWlOffset:
    """GPT header 的 upgrade_tool WL 写入偏移。WL 单位恒为 512 字节，故
    4K 设备上 header（设备 byte 4096）的 WL 偏移 = 8，而非逻辑 LBA 1。
    实板回归：WL 1 把 header 写到 byte 512，u-boot 在 byte 4096 读到垃圾
    → "GPT Header signature is wrong" → abort。"""

    def test_512_unchanged(self):
        # 回归安全：512 设备仍 WL 1（与历史 byte-identical）
        assert RockchipFlashStrategy()._gpt_wl_offset(512) == 1

    def test_4096_is_8(self):
        # 4K 设备：header 在 byte 4096 = 第 8 个 512 块
        assert RockchipFlashStrategy()._gpt_wl_offset(4096) == 8


class TestFlashConfigSectorSize:
    def test_defaults_to_512_when_absent(self, tmp_path):
        """旧 flash-config.json 无 sector_size 字段时回落 512。"""
        p = tmp_path / "flash-config.json"
        p.write_text(
            '{"platform":"rockchip","flash_tool":"upgrade_tool",'
            '"board":"x","product":"default","variant":"debug"}')
        cfg = FlashConfig.from_json(p)
        assert cfg.sector_size == 512

    def test_roundtrip_4096(self, tmp_path):
        cfg = FlashConfig(
            platform="rockchip", flash_tool="upgrade_tool",
            board="radxa-rock-4d", product="default", variant="debug",
            sector_size=4096)
        p = tmp_path / "flash-config.json"
        cfg.to_json(p)
        assert FlashConfig.from_json(p).sector_size == 4096
