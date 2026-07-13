"""RK3506B SoC 的 ARM32、FIT、TOS 与 AMP 配置契约测试。"""

from builder.config.registry import _load_soc_config


def test_rk3506b_soc_uses_requested_kernel_and_armhf_routes():
    soc = _load_soc_config("rk3506b")
    kernel = soc["kernel"]

    assert soc["platform"] == "rockchip"
    assert soc["soc"] == "rk3506b"
    assert soc["arch"] == "armhf"
    assert kernel["repo"] == (
        "ssh://git@gitlab-r.eric3u.xyz:20022/argon/kernel.git"
    )
    assert kernel["branch"] == "linux-6.1-stan-rkr5.1"
    assert kernel["arch"] == "arm"
    assert kernel["cross_compile"] == (
        "/opt/arm-linux-gcc10/bin/arm-none-linux-gnueabihf-"
    )
    assert kernel["image"] == "zImage"
    assert kernel["dts_dir"] == ""
    assert kernel["boot_format"] == "fit"
    assert kernel["boot_its"] == "boot.its"
    assert kernel["defconfig"] == [
        "rk3506_defconfig",
        "case_insensitive_fix.config",
    ]


def test_rk3506b_soc_uses_radxa_tos_and_newidb_contract():
    soc = _load_soc_config("rk3506b")
    bootloader = soc["bootloader"]
    rkbin = soc["rkbin"]

    assert bootloader["repo"] == "https://github.com/radxa/u-boot"
    assert bootloader["branch"] == "next-dev-v2026.01"
    assert bootloader["cross_compile"] == (
        "/opt/arm-linux-gcc10/bin/arm-none-linux-gnueabihf-"
    )
    assert bootloader["defconfig"] == [
        "rk3506_defconfig",
        "rk3506b.config",
    ]
    assert bootloader["trust_mode"] == "tos"
    assert bootloader["idbloader_method"] == "boot_merger"
    assert bootloader["idbloader_selfbuilt_spl"] is True
    assert bootloader["fit_pack"] == {
        "external_data_offset": "0x1200",
        "slot_size_kb": 2048,
        "copies": 2,
    }
    assert "0004-skip-dtb-bootargs-merge.patch" in (
        bootloader["exclude_patches"]
    )
    assert rkbin == {
        "ini_prefix": "RK3506B",
        "loader_ini": "RK3506BMINIALL.ini",
        "trust_ini": "RK3506TOS.ini",
        "mkimage_chip": "rk3506",
    }


def test_rk3506b_amp_memory_runtime_matches_vendor_dts_and_its():
    amp = _load_soc_config("rk3506b")["amp"]

    assert amp["soc_project"] == "rk3506"
    assert amp["max_image_size"] == "1M"
    assert amp["memory"] == {
        "cpu": 2,
        "cpu_base": 0x03E00000,
        "dram_size": 0x00100000,
        "sram_base": 0xFFF80000,
        "sram_size": 0x0000C000,
        "shmem_base": 0x03B00000,
        "shmem_size": 0x00100000,
        "rpmsg_base": 0x03C00000,
        "rpmsg_size": 0x00200000,
    }
    runtime = amp["runtime"]
    assert runtime["amp_mpidr"] == 0xF02
    assert runtime["linux_mpidr"] == 0xF00
    assert runtime["linux_load"] == 0x00900000
    assert runtime["cpu_delete"] == "cpu@f02"
    assert runtime["link_id"] == 0x02
    assert runtime["mailboxes"] == ["mailbox0", "mailbox2"]
    assert runtime["mailbox_irq"] == 176
    assert runtime["endpoint_address"] == 0x3003
    assert runtime["endpoint_name"] == "rpmsg-ap3-ch0"
    assert runtime["gic_profile"] == "rk3506-stock-mailbox2"
    assert runtime["firmware_reserved_in_dts"] is True
    assert runtime["fit_requires_sram"] is True


def test_rk3506b_soc_only_selects_armhf_rootfs_base_without_board_policy():
    soc = _load_soc_config("rk3506b")

    assert soc["rootfs"]["url"].endswith(
        "ubuntu-base-24.04.4-base-armhf.tar.gz"
    )
    assert soc["rootfs"]["emulator"] == "qemu-arm-static"
    assert "image_format" not in soc["rootfs"]
    assert "custom_packages" not in soc["rootfs"]
    assert "local_path" not in soc["kernel"]
    assert "/Users/" not in repr(soc)
