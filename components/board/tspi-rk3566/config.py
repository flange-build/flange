"""TSpi RK3566 板级配置"""

BOARD = {
    "board": "tspi-rk3566",
    "soc": "rk3566",
    "platform": "rockchip",
    "kernel": {
        "dts": "tspi-rk3566-user-v10-ext39-linux",
    },
    "boot": {
        # 无刷电机 (BLDC/FOC) 引脚 overlay：源在 dtso/tspi-rk3566-bldc.dtso，
        # 由 device-tree-overlay 组件编译进 boot.img。仅构建、默认不应用——
        # 未列入 default_overlays。需启用时把该名加到 default_overlays 重建，
        # 或运行时在 extlinux.conf 的 fdtoverlays 行追加后重启。
        "board_overlays": ["tspi-rk3566-bldc.dtbo"],
    },
    "rootfs": {
        # 账号体系沿用 components/rootfs/config.py base 层默认：
        # root 完全锁定 (root_password=None + disable_root_login=True)，
        # 默认用户 flange/flange 入 sudo group。如需开放 root 或换用户
        # 在此处覆盖（参见 base config docstring 字段速查）。
        "+extra_firmware": [
            {
                "name": "radxa",
                "repo": "https://github.com/radxa-pkg/radxa-firmware",
                "branch": "main",
                "repo_subdir": "radxa-firmware/lib/firmware",
                "files": [
                    "brcm/fw_bcm43438a1.bin",
                    "brcm/nvram_ap6212a.txt",
                    "brcm/bcm43438a1.hcd",
                    "brcm/BCM43430A1.hcd",
                ],
                "dest": "lib/firmware",
            }
        ],
    },
}
