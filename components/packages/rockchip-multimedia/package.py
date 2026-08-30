"""Rockchip MPP、RGA 与 GStreamer 硬件加速软件包集合。

这条编译链被拆成 8 个单元 App，每个由 flange 的 per-App 缓存独立判定是否
重建 —— 改一个补丁只重编相关单元与其下游，包内不再自建增量机制。

单元间的编译期依赖走两条平行声明，必须保持一致（由
``tests/builder/test_rockchip_multimedia_units.py`` 对账）：
  - ``app.yaml`` 的 ``build.deps``：flange 用它排序并做缓存的 Merkle 级联；
  - ``lib/toolkit.py`` 的 ``Unit.deps``：脚本用它合成 sysroot。

``inputs`` 声明位于 App 目录之外、但确实参与构建的包内内容 —— 共享的构建
逻辑与该单元自己的补丁子目录；不声明就不会进 App 的内容哈希。
"""

# 四个 GStreamer 编译单元只产出供下游消费的 staging 树（type=staging），不打
# deb；它们的产物由 rkmm-gst-repack 按 Ubuntu Noble 的分包边界重打成 14 个
# deb —— 分包边界与编译单元边界不重合，故重打是独立一步。
_LIB = "lib"

PACKAGE = {
    "name": "rockchip-multimedia",
    "description": "Rockchip 多媒体硬件加速 runtime",
    "components": [
        {
            "type": "vendor",
            "name": "rkmm-mpp",
            "dir": "units/rkmm-mpp",
            "inputs": [_LIB],
        },
        {
            "type": "vendor",
            "name": "rkmm-rga",
            "dir": "units/rkmm-rga",
            "inputs": [_LIB],
        },
        {
            "type": "vendor",
            "name": "rkmm-gstreamer",
            "dir": "units/rkmm-gstreamer",
            "inputs": [_LIB, "patches/gstreamer"],
        },
        {
            "type": "vendor",
            "name": "rkmm-gst-base",
            "dir": "units/rkmm-gst-base",
            "inputs": [_LIB, "patches/gst-plugins-base"],
        },
        {
            "type": "vendor",
            "name": "rkmm-gst-good",
            "dir": "units/rkmm-gst-good",
            "inputs": [_LIB, "patches/gst-plugins-good"],
        },
        {
            "type": "vendor",
            "name": "rkmm-gst-bad",
            "dir": "units/rkmm-gst-bad",
            "inputs": [_LIB, "patches/gst-plugins-bad"],
        },
        {
            "type": "vendor",
            "name": "rkmm-gst-rockchip",
            "dir": "units/rkmm-gst-rockchip",
            "inputs": [_LIB],
        },
        {
            "type": "vendor",
            "name": "rkmm-gst-repack",
            "dir": "units/rkmm-gst-repack",
            "inputs": [_LIB],
        },
        {
            "type": "vendor",
            "name": "flange-rockchip-multimedia",
            "dir": "config",
        },
    ],
}
