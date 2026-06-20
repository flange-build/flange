"""Rockchip 刷写存储定向（UFS=SATA）测试。

UFS 在 Rockchip 工具链里叫 "SATA"。`upgrade_tool SSD` 列出存储，`SSD <No>`
切换。flange 必须在 DB 之后把存储切到 UFS，否则 WL 默认写进 SPI NOR。
"""

from __future__ import annotations

from builder.flash import RockchipFlashStrategy

SSD_LIST = """Using .../config.ini
List of supported storage
No=1\tFLASH
No=2\tEMMC
No=3\tSD
No=4\tSD1
No=5\tSPINOR
No=6\tSPINAND
No=7\tRAM
No=8\tUSB
No=9\tSATA(*)
No=10\tPCIE
Input No to switch,Quit press <Q>:"""


class TestParseStorageNo:
    def test_finds_sata_index(self):
        # SATA(*) 当前激活标记须被忽略，仅匹配名字
        assert RockchipFlashStrategy._parse_storage_no(SSD_LIST, "SATA") == "9"

    def test_finds_emmc_index(self):
        assert RockchipFlashStrategy._parse_storage_no(SSD_LIST, "EMMC") == "2"

    def test_case_insensitive(self):
        assert RockchipFlashStrategy._parse_storage_no(SSD_LIST, "sata") == "9"

    def test_missing_returns_none(self):
        assert RockchipFlashStrategy._parse_storage_no(SSD_LIST, "NVME") is None
