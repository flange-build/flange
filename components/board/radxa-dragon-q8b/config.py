"""Radxa Dragon Q8B（Qualcomm SC8280XP）板级配置。"""

RADXA_FIRMWARE_REPO = "https://github.com/radxa-pkg/radxa-firmware.git"
RADXA_FIRMWARE_COMMIT = "e1761009df008adfd62c77f2c5584e3067449013"

BOARD = {
    "board": "radxa-dragon-q8b",
    "soc": "sc8280xp",
    "platform": "qualcommsc8280xp",
    "packages": [
        "firmware-qcom-audioreach",
        "radxa-q8b-fastrpc",
    ],
    "kernel": {
        "dtb": "sc8280xp-radxa-dragon-q8b",
    },
    "rootfs": {
        "+groups": ["fastrpc"],
        "+packages": ["acl", "libbsd0", "libyaml-0-2", "udev"],
        "+extra_firmware": [
            {
                "name": "radxa-firmware-sc8280xp",
                "repo": RADXA_FIRMWARE_REPO,
                "commit": RADXA_FIRMWARE_COMMIT,
                "repo_subdir": "radxa-firmware-sc8280xp/lib/firmware",
                "files": [
                    "qcom/sc8280xp/qccdsp8280.mbn",
                    "qcom/sc8280xp/qcslpi8280.mbn",
                    "qcom/sc8280xp/qcvss8280.mbn",
                    "qcom/sc8280xp/qupv3fw.elf",
                    "qcom/sc8280xp/radxa/dragon-q8b/qcadsp8280.mbn",
                    "qcom/vpu/vpu20_p4_gen2_s6.mbn",
                    {
                        "src": "qcom/sc8280xp/qcdxkmsuc8280.mbn",
                        "dest": (
                            "qcom/sc8280xp/LENOVO/21BX/"
                            "qcdxkmsuc8280.mbn"
                        ),
                    },
                ],
                "dest": "lib/firmware",
            },
        ],
        "+extra_debs": [
            {
                "name": "alsa-ucm-conf-radxa-q8b",
                "url": (
                    "https://github.com/radxa-pkg/alsa-ucm-conf/releases/"
                    "download/1.2.16.1-radxa-1/"
                    "alsa-ucm-conf_1.2.16.1-radxa-1_all.deb"
                ),
                "sha256": (
                    "e98278426a43fac2b99f72d299032c2904b62886c3a6fb1"
                    "f745f5ad0c3bc62e8"
                ),
                "filename": "alsa-ucm-conf_1.2.16.1-radxa-1_all.deb",
            },
        ],
    },
}
