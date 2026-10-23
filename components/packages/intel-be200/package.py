"""intel-be200 硬件特性包清单。

Intel Wi-Fi 7 BE200（M.2 PCIe，``8086:272b``，零售版 GL C0 步进）。驱动来自
Intel 官方 backport-iwlwifi，作为 OOT 模块对目标内核编译；内核侧 Kconfig、
OOT 编译、固件与用户态包在同目录 ``config.jsonnet`` 中声明，与板卡和平台无关。

``driver/bt``（oot-driver）为板载蓝牙（USB ``8087:0036``，Gale Peak 2）：以目标
内核自带 btusb/btintel 为底补上设备 ID 与 hw_variant 0x1c 后编译，装入
``updates/`` 覆盖树内同名模块；固件 ``intel/ibt-0291-0291.{sfi,ddc}``。

``runtime``（vendor）装入运行时调优：NetworkManager 对 iwlwifi 设备关闭 Wi-Fi
节能；udev 在网卡出现时按 ``cpu_capacity`` 把中断绑到高性能核（大小核 SoC 上
避免单流软中断落在小核）。
"""

PACKAGE = {
    "name": "intel-be200",
    "description": "Intel Wi-Fi 7 BE200 PCIe 网卡与蓝牙（backport-iwlwifi + gl-c0 / ibt-0291 固件）",
    "components": [
        {
            "type": "oot-driver",
            "name": "bt",
            "dir": "driver/bt",
            "ko_pattern": ["btusb.ko", "btintel.ko"],
        },
        {"type": "vendor", "name": "flange-intel-be200", "dir": "runtime"},
    ],
}
