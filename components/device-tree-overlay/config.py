"""device-tree-overlay 组件默认配置。

该组件从外部 vendor overlay 仓库（radxa-overlays）按 ``boot.vendor_overlays``
列表用 cpp + dtc 编译 ``.dtbo``，与内核源码树内的 in-tree overlay 形成两源
平铺到 boot.img 的 ``/dtbs/<vendor>/overlay/``。

source 声明（git repo + tag）放在这里而非各 platform config，原因：
- radxa-overlays 是单仓库覆盖 rockchip / allwinner / amlogic / qcom 多家
  vendor，git 来源应一处声明，不能 N 家 N 份
- 升级仅改一个 tag，所有平台同步生效
- 内容哈希基于该 tag，tag 改变即触发整链增量重 build

各 platform / SoC / board 仍可在自己的 config 中覆盖（如 pin 不同 tag），
deep_merge 走标准三层。
"""

DEVICE_TREE_OVERLAY = {
    "device-tree-overlay": {
        "repo": "https://github.com/radxa-pkg/radxa-overlays.git",
        # branch 字段在 SourceManager 中等价于 git ref，可以是 tag / branch /
        # commit。这里 pin 到具体 release tag，避免 main 漂移。
        "branch": "0.2.21",
    },
    "boot": {
        # 默认空：未声明则 device-tree-overlay 组件 short-circuit，仅 fetch
        # 源码（保持内容哈希稳定），不执行任何 cpp / dtc 调用。
        "vendor_overlays": [],
    },
}
