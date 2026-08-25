"""按 FINAL_CONFIG 构建路由解析缓存哈希与必需产物。"""

from __future__ import annotations

from builder.cache import BuildCache


def _config(parameter=None) -> dict:
    partitions = {"format": "mtd"}
    if parameter is not None:
        partitions["parameter"] = str(parameter)
    return {
        "board": "cache-route-test",
        "product": "default",
        "variant": "release",
        "architecture": {
            "userspace": "armhf", "kernel": "arm", "bootloader": "arm",
        },
        "platform": "rockchip",
        "soc": "rk3506b",
        "kernel": {
            "cross_compile": "arm-linux-gnueabihf-",
            "image": "zImage",
            "device_tree": {"directory": "", "name": "rk3506b-test"},
            "boot_format": "fit",
            "boot_its": "boot.its",
        },
        "rootfs": {
            "url": "https://example.invalid/ubuntu-base-armhf.tar.gz",
            "packages": [],
            "custom_packages": [],
            "image_format": "ubi",
            "ubi": {
                "min_io_size": 2048,
                "peb_size": 131072,
                "leb_size": 126976,
                "volume_size": "400M",
            },
        },
        "partitions": partitions,
        "recovery": {"enabled": False},
        "amp": {"enabled": False},
        "boot": {},
        "bootloader": {},
    }


def test_arm32_fit_kernel_cache_requires_exact_dtb_and_boot_img(tmp_path):
    cache = BuildCache(_config(), target_base=tmp_path)
    kernel_dir = cache.target_dir / "kernel"
    kernel_dir.mkdir(parents=True)
    (kernel_dir / "Image").write_bytes(b"wrong-arch-image")
    (kernel_dir / "rk3506b-test.dtb").write_bytes(b"dtb")

    assert cache._required_artifacts("kernel") == [
        "zImage", "rk3506b-test.dtb", "boot.img"
    ]
    assert not cache._required_artifacts_present("kernel")

    (kernel_dir / "zImage").write_bytes(b"arm-zimage")
    (kernel_dir / "stale-other-board.dtb").write_bytes(b"stale")
    assert not cache._required_artifacts_present("kernel")

    (kernel_dir / "boot.img").write_bytes(b"fit")
    assert cache._required_artifacts_present("kernel")

    (kernel_dir / "rk3506b-test.dtb").unlink()
    assert not cache._required_artifacts_present("kernel")

    (kernel_dir / "rk3506b-test.dtb").write_bytes(b"dtb")
    assert cache._required_artifacts_present("kernel")


def test_ubi_cache_requires_rootfs_ubi_not_ext4_image(tmp_path):
    cache = BuildCache(_config(), target_base=tmp_path)
    rootfs_dir = cache.target_dir / "rootfs"
    rootfs_dir.mkdir(parents=True)
    (rootfs_dir / "rootfs.img").write_bytes(b"ext4")

    assert cache._required_artifacts("rootfs") == ["rootfs.ubi"]
    assert not cache._required_artifacts_present("rootfs")

    (rootfs_dir / "rootfs.ubi").write_bytes(b"UBI#")
    assert cache._required_artifacts_present("rootfs")


def test_mtd_image_cache_requires_bundle_manifest_not_raw_img(tmp_path):
    cache = BuildCache(_config(), target_base=tmp_path)
    image_dir = cache.target_dir / "image"
    image_dir.mkdir(parents=True)
    (image_dir / "raw.img").write_bytes(b"gpt")

    assert cache._required_artifacts("image") == ["mtd-bundle.json"]
    assert not cache._required_artifacts_present("image")

    (image_dir / "mtd-bundle.json").write_text("{}")
    assert cache._required_artifacts_present("image")


def test_gpt_ext4_defaults_keep_existing_required_artifacts(tmp_path):
    config = _config()
    config["architecture"] = {
        "userspace": "aarch64", "kernel": "arm64", "bootloader": "arm",
    }
    config["kernel"] = {
        "device_tree": {"directory": "rockchip", "name": "rk3566-test"},
    }
    config["rootfs"] = {
        "url": "https://example.invalid/ubuntu-base-arm64.tar.gz",
        "packages": [],
        "custom_packages": [],
    }
    config["partitions"] = {"format": "gpt", "entries": []}
    cache = BuildCache(config, target_base=tmp_path)

    assert cache._required_artifacts("kernel") == [
        "Image", "rk3566-test.dtb"
    ]
    assert cache._required_artifacts("rootfs") == ["rootfs.img"]
    assert cache._required_artifacts("image") == ["raw.img"]


def test_ubi_geometry_changes_rootfs_hash(tmp_path):
    config_a = _config()
    config_b = _config()
    config_b["rootfs"]["ubi"]["peb_size"] = 262144

    hash_a = BuildCache(config_a, target_base=tmp_path).compute_hash("rootfs")
    hash_b = BuildCache(config_b, target_base=tmp_path).compute_hash("rootfs")

    assert hash_a != hash_b


def test_ubi_space_fixup_changes_rootfs_hash(tmp_path):
    config_a = _config()
    config_b = _config()
    config_b["rootfs"]["ubi"]["space_fixup"] = True

    hash_a = BuildCache(config_a, target_base=tmp_path).compute_hash("rootfs")
    hash_b = BuildCache(config_b, target_base=tmp_path).compute_hash("rootfs")

    assert hash_a != hash_b


def test_parameter_content_changes_rootfs_and_image_hash(tmp_path):
    parameter = tmp_path / "parameter.txt"
    parameter.write_text(
        "CMDLINE:mtdparts=:0x1000@0x0(boot),-@0x1000(rootfs)\n")
    config = _config(parameter)
    first = BuildCache(config, target_base=tmp_path)
    rootfs_hash_a = first.compute_hash("rootfs")
    image_hash_a = first.compute_hash("image")

    parameter.write_text(
        "CMDLINE:mtdparts=:0x2000@0x0(boot),-@0x2000(rootfs)\n")
    second = BuildCache(config, target_base=tmp_path)

    assert rootfs_hash_a != second.compute_hash("rootfs")
    assert image_hash_a != second.compute_hash("image")
