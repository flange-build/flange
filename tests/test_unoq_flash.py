"""UNO Q 发布包和刷写边界测试；设备交互全用替身，绝不访问 USB。"""

import json
import struct
import subprocess
import uuid
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

import pytest

from builder.flash import unoq
from builder.flash.execute import FlashExecutor
from builder.flash.generate import FlashConfigGenerator
from builder.flash.model import DeviceInfo, FlashError


def gpt_pair(sectors=unoq.USER_START + 33, *, root_sectors=None,
             attributes=None, guid_seed=""):
    """独立生成 72 项测试 GPT，不依赖被测重算函数。"""
    rootsize = root_sectors or unoq.USER_START - unoq.ROOT_START
    user_start = unoq.ROOT_START + rootsize
    parts = [(name, 40 + i * 16, 16) for i, name in enumerate(sorted(unoq.PRESERVED))]
    parts += [("xbl_a", 131072, 7168), ("xbl_b", 138240, 7168),
              ("boot_a", 166400, 8192), ("boot_b", 174592, 8192),
              ("uefi_a", 200000, 16), ("uefi_b", 200016, 16),
              ("efi", unoq.EFI_START, 1048576),
              ("rootfs", unoq.ROOT_START, rootsize),
              ("userdata", user_start, sectors - 33 - user_start)]
    entries = bytearray(72 * 128)
    for index, (name, start, size) in enumerate(parts):
        offset = index * 128
        entries[offset:offset + 16] = uuid.uuid5(uuid.NAMESPACE_DNS, "type-" + name).bytes_le
        entries[offset + 16:offset + 32] = uuid.uuid5(
            uuid.NAMESPACE_DNS, guid_seed + name).bytes_le
        struct.pack_into("<QQ", entries, offset + 32, start, start + size - 1)
        flags = (attributes or {}).get(name, 0x1000000000000000
                                      if name.endswith(("_a", "_b")) else 0)
        struct.pack_into("<Q", entries, offset + 48, flags)
        namebytes = name.encode("utf-16-le")
        entries[offset + 56:offset + 56 + len(namebytes)] = namebytes
    outputs = []
    for backup in (False, True):
        data = bytearray((33 if backup else 34) * 512)
        if not backup:
            data[510:512] = b"\x55\xaa"
            data[450] = 0xee
            struct.pack_into("<II", data, 454, 1, sectors - 1)
        offset = 0 if backup else 1024
        data[offset:offset + len(entries)] = entries
        header = bytearray(92)
        header[:8] = b"EFI PART"
        struct.pack_into("<II", header, 8, 0x10000, 92)
        struct.pack_into("<4Q", header, 24, sectors - 1 if backup else 1,
                         1 if backup else sectors - 1, 34, sectors - 34)
        header[56:72] = uuid.uuid5(
            uuid.NAMESPACE_DNS, guid_seed + "test-unoq-disk").bytes_le
        struct.pack_into("<QIII", header, 72, sectors - 33 if backup else 2,
                         72, 128, zlib.crc32(entries))
        struct.pack_into("<I", header, 16, zlib.crc32(header))
        offset = 32 * 512 if backup else 512
        data[offset:offset + len(header)] = header
        outputs.append(bytes(data))
    return tuple(outputs)


def refresh_manifest(bundle):
    path = bundle / unoq.MANIFEST
    metadata = json.loads(path.read_text())
    for name, item in metadata["files"].items():
        data = bundle / name
        item.update(sha256=unoq.digest(data), bytes=data.stat().st_size)
    path.write_text(json.dumps(metadata))


@pytest.fixture
def bundle(tmp_path):
    firmware = tmp_path / "firmware"
    firmware.mkdir()
    primary, backup = gpt_pair()
    (firmware / "gpt_main0.bin").write_bytes(primary)
    (firmware / "gpt_backup0.bin").write_bytes(backup)
    (firmware / "LICENSE").write_text("测试固件许可")
    (firmware / "LICENSE.arduino").write_text("测试固件来源")
    (firmware / "patch0.xml").write_text("<patches />")
    (firmware / unoq.LOADER).write_bytes(b"test-loader")
    (firmware / "xbl.elf").write_bytes(b"test-xbl")
    (firmware / "boot.img").write_bytes(b"test-uboot")
    table = unoq.parse_gpt(primary, template=True)
    filenames = {"boot_a": "boot.img", "boot_b": "boot.img",
                 "xbl_a": "xbl.elf", "xbl_b": "xbl.elf",
                 "efi": "../disk-sdcard.img.esp", "rootfs": "../disk-sdcard.img.root",
                 "userdata": "../disk-sdcard.img.home"}
    nodes = []
    for entry in table.entries.values():
        nodes.append({"label": entry.name, "filename": filenames.get(entry.name, ""),
                      "start_sector": str(entry.first), "num_partition_sectors": str(entry.sectors),
                      "physical_partition_number": "0", "SECTOR_SIZE_IN_BYTES": "512",
                      "file_sector_offset": "0", "sparse": "false"})
    for label, name, start, size in (("PrimaryGPT", "gpt_main0.bin", "0", "34"),
                                    ("BackupGPT", "gpt_backup0.bin", "NUM_DISK_SECTORS-33.", "33")):
        nodes.append({"label": label, "filename": name, "start_sector": start,
                      "num_partition_sectors": size, "physical_partition_number": "0",
                      "SECTOR_SIZE_IN_BYTES": "512", "sparse": "false"})
    unoq.write_xml(firmware / "rawprogram0.xml", nodes)
    images = {}
    for label, size in (("boot_a", 900), ("efi", 1024), ("rootfs", 4097), ("userdata", 600)):
        image = tmp_path / (label + ".img")
        image.write_bytes(b"x" * size)
        images[label] = image
    output = tmp_path / "target" / unoq.BUNDLE_PATH
    unoq.build_bundle(firmware, images, output)
    return output


def configured(bundle):
    target = bundle.parent.parent
    config = unoq.make_flash_config({"board": "arduino-uno-q"}, target)
    return target, config


def prepared(monkeypatch, bundle, *, sectors=30_535_680, names=None, root_sectors=None,
             attributes=None, guid_seed=""):
    target, config = configured(bundle)
    strategy = unoq.UnoQFlashStrategy()
    strategy.allow_protected = True
    selected = [p for p in config.partitions if names is None or p.name in names]
    strategy.preflight(target, config, selected)
    device = DeviceInfo("qualcommqrb2210", "edl", "测试设备", "ABCDEF12")
    monkeypatch.setattr(strategy, "detect_device", lambda tool: device)
    monkeypatch.setattr(strategy, "wait_for_device", lambda tool: device)
    calls = []
    def run(tool, directory, xml, **kwargs):
        calls.append(xml)
        if xml.name == "read-gpt.xml":
            primary, backup = gpt_pair(
                sectors, root_sectors=root_sectors, attributes=attributes, guid_seed=guid_seed)
            (directory / "primary.bin").write_bytes(primary)
            (directory / "backup.bin").write_bytes(backup)
    monkeypatch.setattr(strategy, "_run", run)
    strategy.pre_flash(Path("qdl"), target, config, device)
    return strategy, config, calls


def test_bundle_maps_uboot_and_efi_and_preserves_empty_regions(bundle):
    metadata, table, nodes = unoq.validate_bundle(bundle)
    assert metadata["storage"] == "emmc"
    written = {node["label"]: node["filename"] for node in nodes}
    assert written["boot_a"] == written["boot_b"] == "files/uboot-boot.img"
    assert written["efi"] == "files/efi.img"
    assert not set(written) & unoq.PRESERVED
    assert set(unoq.PRESERVED) <= table.entries.keys()


@pytest.mark.parametrize("filename", ["files/rootfs.img", "files/prog_firehose_ddr.elf"])
def test_missing_required_image_fails(bundle, filename):
    (bundle / filename).unlink()
    with pytest.raises(FlashError):
        unoq.validate_bundle(bundle)


def test_finder_metadata_does_not_invalidate_bundle(bundle):
    for directory in (bundle, bundle / "files"):
        (directory / ".DS_Store").write_bytes(b"Finder metadata")
    unoq.validate_bundle(bundle)


def test_unexpected_file_reports_exact_difference(bundle):
    (bundle / "unexpected.img").write_bytes(b"unexpected")
    (bundle / "files/rootfs.img").unlink()
    with pytest.raises(FlashError) as failure:
        unoq.validate_bundle(bundle)
    assert "unexpected.img" in str(failure.value)
    assert "files/rootfs.img" in str(failure.value)


@pytest.mark.parametrize("exists", [True, False])
def test_finder_metadata_symlink_is_not_exempt(bundle, tmp_path, exists):
    outside = tmp_path / "outside-metadata"
    if exists:
        outside.write_bytes(b"outside")
    (bundle / ".DS_Store").symlink_to(outside)
    with pytest.raises(FlashError, match="额外=.*DS_Store"):
        unoq.validate_bundle(bundle)


def test_tampered_image_and_manifest_schema_fail(bundle):
    (bundle / "files/rootfs.img").write_bytes(b"tampered")
    with pytest.raises(FlashError, match="摘要或长度"):
        unoq.validate_bundle(bundle)
    manifest_path = bundle / unoq.MANIFEST
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["files/rootfs.img"] = "not-an-object"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(FlashError, match="元数据类型"):
        unoq.validate_bundle(bundle)


@pytest.mark.parametrize("name", ["../escape", "/tmp/escape", "files/../rootfs.img", "files\\escape"])
def test_path_traversal_fails(bundle, name):
    with pytest.raises(FlashError, match="不安全"):
        unoq.safe_file(bundle, name)


def test_symlink_escape_fails(bundle, tmp_path):
    image = bundle / "files/rootfs.img"
    image.unlink()
    outside = tmp_path / "outside"
    outside.write_bytes(b"x" * 4097)
    image.symlink_to(outside)
    with pytest.raises(FlashError, match="符号链接"):
        unoq.validate_bundle(bundle)


@pytest.mark.parametrize("payload", [
    b'<!DOCTYPE data [<!ENTITY x SYSTEM "file:///etc/passwd">]><data>&x;</data>',
    '<!DOCTYPE data [<!ENTITY x "abc">]><data>&x;</data>'.encode("utf-16"),
    b'<data><erase start_sector="0" /></data>',
    b'<data><program><erase /></program></data>',
])
def test_unsafe_xml_fails(tmp_path, payload):
    source = tmp_path / "bad.xml"
    source.write_bytes(payload)
    with pytest.raises(FlashError):
        unoq.read_xml(source, "data", "program")


def test_misaligned_xml_geometry_fails_even_with_updated_digest(bundle):
    xml = bundle / "rawprogram0.xml"
    root = ET.parse(xml)
    next(node for node in root.getroot() if node.get("label") == "rootfs").set("start_sector", "12")
    root.write(xml)
    refresh_manifest(bundle)
    with pytest.raises(FlashError, match="几何不一致"):
        unoq.validate_bundle(bundle)


def test_oversized_boot_image_fails(bundle):
    image = bundle / "files/uboot-boot.img"
    with image.open("wb") as stream:
        stream.truncate(4 * 1024 ** 2 + 1)
    refresh_manifest(bundle)
    with pytest.raises(FlashError, match="超出分区容量"):
        unoq.validate_bundle(bundle)


def test_gpt_crc_and_backup_mismatch_fail():
    primary, backup = gpt_pair(30_535_680)
    altered = bytearray(primary)
    altered[520] ^= 1
    with pytest.raises(FlashError):
        unoq.parse_gpt(bytes(altered))
    altered = bytearray(primary)
    altered[1100] ^= 1
    with pytest.raises(FlashError, match="数组 CRC"):
        unoq.parse_gpt(bytes(altered))
    other_primary, other_backup = gpt_pair(61_071_360)
    with pytest.raises(FlashError, match="主备 GPT 不一致"):
        unoq.validate_pair(unoq.parse_gpt(primary), unoq.parse_gpt(other_backup, backup=True))


@pytest.mark.parametrize("first,last,error", [(56, 71, "重叠"), (1, 16, "越界"),
                                             (30_535_650, 30_535_660, "越界")])
def test_gpt_invalid_ranges_fail_after_valid_crcs(first, last, error):
    primary, _ = gpt_pair(30_535_680)
    data = bytearray(primary)
    struct.pack_into("<QQ", data, 1024 + 32, first, last)
    struct.pack_into("<I", data, 512 + 88, zlib.crc32(data[1024:1024 + 72 * 128]))
    struct.pack_into("<I", data, 512 + 16, 0)
    struct.pack_into("<I", data, 512 + 16, zlib.crc32(data[512:512 + 92]))
    with pytest.raises(FlashError, match=error):
        unoq.parse_gpt(bytes(data))


def test_bundle_copy_keeps_sparse_rootfs(bundle, monkeypatch):
    # GNU cp 即使存在也可能不支持共享文件系统；组包不能依赖该外部调用。
    def unexpected_command(*args, **kwargs):
        pytest.fail("稀疏镜像复制不应调用外部 cp")

    monkeypatch.setattr(unoq.subprocess, "run", unexpected_command)
    root = bundle.parent.parent.parent
    image = root / "rootfs.img"
    with image.open("ab") as stream:
        stream.truncate(64 * 1024 ** 2)
    images = {label: root / (label + ".img") for label in ("boot_a", "efi", "rootfs", "userdata")}
    result = unoq.build_bundle(root / "firmware", images, root / "sparse-bundle")
    copied = result / "files/rootfs.img"
    assert copied.stat().st_size == 64 * 1024 ** 2
    assert copied.stat().st_blocks * 512 < copied.stat().st_size // 4


def test_sparse_copy_preserves_data_tail_and_permissions(tmp_path):
    source, destination = tmp_path / "source", tmp_path / "destination"
    data = b"header" + bytes(3 * 1024 ** 2) + b"middle" + bytes(2 * 1024 ** 2 + 17)
    source.write_bytes(data)
    source.chmod(0o640)
    unoq.copy_sparse_image(source, destination)
    assert destination.read_bytes() == data
    assert destination.stat().st_mode & 0o777 == 0o640


def test_sparse_copy_reports_original_io_failure(tmp_path, monkeypatch):
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.write_bytes(b"payload")
    original_open = Path.open

    def no_space(path, *args, **kwargs):
        if path == destination:
            raise OSError(28, "No space left on device")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", no_space)
    with pytest.raises(FlashError, match="No space left on device") as failure:
        unoq.copy_sparse_image(source, destination)
    assert str(destination) in str(failure.value)
    assert isinstance(failure.value.__cause__, OSError)


@pytest.mark.parametrize("sectors", [30_535_680, 61_071_360])
def test_resize_two_capacities_preserves_fixed_entries_and_updates_both_crcs(sectors):
    original, _ = gpt_pair()
    template = unoq.parse_gpt(original, template=True)
    primary, backup = unoq.resize_gpt(template, sectors)
    actual = unoq.parse_gpt(primary)
    back = unoq.parse_gpt(backup, backup=True)
    unoq.validate_pair(actual, back)
    assert actual.sectors == sectors
    assert actual.entries["userdata"].last == sectors - 34
    assert back.table_lba == sectors - 33
    for name, entry in template.entries.items():
        if name != "userdata":
            assert actual.entries[name] == entry


def test_flash_generator_publishes_real_partition_names_and_manifest_digest(bundle):
    target, config = configured(bundle)
    path = FlashConfigGenerator().generate({"platform": "qualcommqrb2210", "board": "arduino-uno-q"}, target)
    assert json.loads(path.read_text())["bundle_manifest_sha256"] == unoq.digest(bundle / unoq.MANIFEST)
    assert {"boot_a", "boot_b", "efi", "rootfs", "userdata"} <= {p.name for p in config.partitions}


@pytest.mark.parametrize("sectors,root_size", [(30_535_680, None), (61_071_360, 20 * 1024 ** 3 // 512)])
def test_rootfs_only_never_writes_gpt_firmware_userdata(monkeypatch, bundle, sectors, root_size):
    strategy, config, calls = prepared(monkeypatch, bundle, sectors=sectors, names={"rootfs"}, root_sectors=root_size)
    part = next(p for p in config.partitions if p.name == "rootfs")
    strategy.write_named_partition(Path("qdl"), part, strategy.target_dir / part.image, config)
    nodes = list(ET.parse(calls[-1]).getroot())
    assert [n.get("label") for n in nodes] == ["rootfs"]
    assert nodes[0].get("num_partition_sectors") == "9"
    assert nodes[0].get("start_sector") == str(unoq.ROOT_START)
    assert not (strategy.record_dir / "gpt_main0.bin").exists()


def test_full_flash_retains_device_guids_and_userdata_geometry(monkeypatch, bundle):
    strategy, config, calls = prepared(monkeypatch, bundle, sectors=61_071_360,
                                       root_sectors=20 * 1024 ** 3 // 512)
    strategy.flash_whole_disk(Path("qdl"), strategy.target_dir, config)
    nodes = list(ET.parse(calls[-1]).getroot())
    names = {n.get("label") for n in nodes}
    assert {"PrimaryGPT", "BackupGPT", "boot_a", "boot_b", "efi", "rootfs", "userdata"} <= names
    assert not names & unoq.PRESERVED
    user = next(n for n in nodes if n.get("label") == "userdata")
    assert user.get("start_sector") == str(unoq.ROOT_START + 20 * 1024 ** 3 // 512)
    assert user.get("num_partition_sectors") == "2"
    primary = unoq.parse_gpt((strategy.record_dir / "gpt_main0.bin").read_bytes())
    backup = unoq.parse_gpt((strategy.record_dir / "gpt_backup0.bin").read_bytes(), backup=True)
    unoq.validate_pair(primary, backup)
    assert primary.entries == strategy.observed_gpt.entries


@pytest.mark.parametrize("sectors,root_size", [
    (30_535_680, None), (61_071_360, 20 * 1024 ** 3 // 512),
])
def test_full_flash_restores_exhausted_slots_without_changing_other_metadata(
        monkeypatch, bundle, sectors, root_size):
    # 实板故障 boot_a=0x1087...；同时覆盖旧成功位、未写镜像的 A/B 项和非槽位属性。
    attributes = {"boot_a": 0x1087000012345678, "boot_b": 0x1040000087654321,
                  "xbl_a": 0x1004000000000000, "uefi_a": 0x1004000011223344,
                  "persist": 0x1287FEDCBA987654, "rootfs": 0xAB87567812345678}
    strategy, config, calls = prepared(
        monkeypatch, bundle, sectors=sectors, root_sectors=root_size,
        attributes=attributes, guid_seed="real-device-")
    observed = strategy.observed_gpt
    strategy.flash_whole_disk(Path("qdl"), strategy.target_dir, config)
    primary = unoq.parse_gpt((strategy.record_dir / "gpt_main0.bin").read_bytes())
    backup = unoq.parse_gpt((strategy.record_dir / "gpt_backup0.bin").read_bytes(), backup=True)
    unoq.validate_pair(primary, backup)
    assert primary.entries == observed.entries
    assert primary.header[56:72] == observed.header[56:72] != strategy.table.header[56:72]
    assert primary.sectors == observed.sectors
    for name, entry in observed.entries.items():
        offset = entry.index * 128
        before = observed.entries_raw[offset:offset + 128]
        after = primary.entries_raw[offset:offset + 128]
        if name.endswith(("_a", "_b")):
            template_offset = strategy.table.entries[name].index * 128
            assert after[54] == strategy.table.entries_raw[template_offset + 54] == 0
            assert after[:54] == before[:54]
            assert after[55:] == before[55:]
        else:
            assert after == before
    # 恢复元数据不把无镜像项、持久化分区变成擦除或额外写入。
    written = {node.get("label") for node in ET.parse(calls[-1]).getroot()}
    assert not written & (unoq.PRESERVED | {"uefi_a", "uefi_b"})


@pytest.mark.parametrize("name", ["boot_a", "boot_b", "rootfs"])
def test_single_partition_with_exhausted_slot_never_changes_gpt(monkeypatch, bundle, name):
    strategy, config, calls = prepared(
        monkeypatch, bundle, names={name}, attributes={"boot_a": 0x1087000000000000})
    observed = strategy.observed_gpt.data
    part = next(p for p in config.partitions if p.name == name)
    strategy.write_named_partition(Path("qdl"), part, strategy.target_dir / part.image, config)
    assert [node.get("label") for node in ET.parse(calls[-1]).getroot()] == [name]
    assert strategy.observed_gpt.data == observed
    assert not (strategy.record_dir / "gpt_main0.bin").exists()
    assert not (strategy.record_dir / "gpt_backup0.bin").exists()


def test_full_flash_missing_one_boot_slot_cannot_reset_metadata(monkeypatch, bundle):
    strategy, _, calls = prepared(monkeypatch, bundle)
    with pytest.raises(FlashError, match="写入范围"):
        strategy._write(Path("qdl"), strategy.all_names - {"boot_b"}, full=True)
    assert len(calls) == 1
    assert not (strategy.record_dir / "gpt_main0.bin").exists()


@pytest.mark.parametrize("flags", [0x40, 0x80])
def test_recovery_template_cannot_mark_boot_successful_or_unbootable(
        monkeypatch, bundle, flags):
    primary, backup = gpt_pair(attributes={"boot_a": 0x1000000000000000 | (flags << 48)})
    (bundle / "gpt_main0.bin").write_bytes(primary)
    (bundle / "gpt_backup0.bin").write_bytes(backup)
    refresh_manifest(bundle)
    strategy, config, calls = prepared(monkeypatch, bundle)
    with pytest.raises(FlashError, match="不能预设启动成功或不可启动"):
        strategy.flash_whole_disk(Path("qdl"), strategy.target_dir, config)
    assert len(calls) == 1
    assert not (strategy.record_dir / "gpt_main0.bin").exists()


def test_unknown_capacity_fails_before_any_write(monkeypatch, bundle):
    with pytest.raises(FlashError, match="未支持.*实际容量"):
        prepared(monkeypatch, bundle, sectors=25_000_000)


def test_multiple_devices_and_missing_serial_rejected(monkeypatch):
    strategy = unoq.UnoQFlashStrategy()
    device = DeviceInfo("qualcommqrb2210", "edl", "测试", "ABCDEF12")
    monkeypatch.setattr(strategy, "_usb_devices", lambda: [device, device])
    with pytest.raises(FlashError, match="多个"):
        strategy.detect_device(Path("qdl"))
    monkeypatch.setattr(strategy, "_usb_devices", lambda: [DeviceInfo("qualcommqrb2210", "edl", "测试")])
    with pytest.raises(FlashError, match="串号"):
        strategy.detect_device(Path("qdl"))
    assert unoq.edl_serial("QUSB_BULK_SN:ABCDEF12") == "ABCDEF12"
    assert unoq.edl_serial("USB Serial ABCDEF12") == ""


def test_protected_flash_requires_confirmation_and_no_wait_checks_device(monkeypatch, bundle):
    target, config = configured(bundle)
    strategy = unoq.UnoQFlashStrategy()
    with pytest.raises(FlashError, match="--yes"):
        strategy.preflight(target, config, config.partitions)
    root = [p for p in config.partitions if p.name == "rootfs"]
    strategy.preflight(target, config, root)
    monkeypatch.setattr(strategy, "detect_device", lambda tool: None)
    with pytest.raises(FlashError, match="未连接"):
        strategy.pre_flash(Path("qdl"), target, config)


def test_flash_config_tampering_fails_before_hardware(bundle):
    target, config = configured(bundle)
    config.partitions[0].offset = "0x0"
    with pytest.raises(FlashError, match="计划不一致"):
        unoq.UnoQFlashStrategy().preflight(target, config, config.partitions)


def test_executor_routes_rootfs_through_named_plan(monkeypatch, bundle):
    target, config = configured(bundle)
    config.to_json(target / "flash-config.json")
    executor = FlashExecutor(target)
    strategy, _, calls = prepared(monkeypatch, bundle, names={"rootfs"})
    monkeypatch.setattr(executor, "strategy", strategy)
    monkeypatch.setattr(strategy, "find_tool", lambda project: Path("qdl"))
    executor.flash_partition("rootfs", no_wait=True)
    assert [n.get("label") for n in ET.parse(calls[-1]).getroot()] == ["rootfs"]


def test_no_reboot_is_rejected_before_preflight(bundle):
    target, config = configured(bundle)
    config.to_json(target / "flash-config.json")
    with pytest.raises(FlashError, match="不支持 --no-reboot"):
        FlashExecutor(target).flash_partition("rootfs", no_reboot=True)


def test_qdl_argv_binds_serial_and_does_not_allow_missing(monkeypatch, bundle, tmp_path):
    strategy = unoq.UnoQFlashStrategy()
    strategy.bundle = bundle
    strategy.device = DeviceInfo("qualcommqrb2210", "edl", "测试", "ABCDEF12")
    calls = []
    def run(argv, directory, log, timeout):
        calls.append((argv, {"timeout": timeout, "log": log}))
        return 0
    monkeypatch.setattr(unoq, "stream_qdl", run)
    xml = tmp_path / "read.xml"
    strategy._run(Path("/usr/bin/qdl"), tmp_path, xml)
    assert calls[0][0] == ["/usr/bin/qdl", "--storage", "emmc", "--serial", "ABCDEF12",
                           str(bundle / "files" / unoq.LOADER), str(xml)]
    assert "--allow-missing" not in calls[0][0]
    assert calls[0][1]["timeout"] == 60


def test_qdl_failure_is_recorded_and_never_retried(monkeypatch, bundle):
    strategy, config, calls = prepared(monkeypatch, bundle, names={"rootfs"})
    attempts = []
    def fail(*args, **kwargs):
        attempts.append(args)
        raise FlashError("模拟设备断开")
    monkeypatch.setattr(strategy, "_run", fail)
    part = next(p for p in config.partitions if p.name == "rootfs")
    with pytest.raises(FlashError, match="断开"):
        strategy.write_named_partition(Path("qdl"), part, strategy.target_dir / part.image, config)
    assert len(attempts) == 1
    assert json.loads((strategy.record_dir / "record.json").read_text())["status"] == "failed"


def test_mismatched_hardware_gpt_never_reaches_program(monkeypatch, bundle):
    target, config = configured(bundle)
    strategy = unoq.UnoQFlashStrategy()
    strategy.preflight(target, config, [p for p in config.partitions if p.name == "rootfs"])
    device = DeviceInfo("qualcommqrb2210", "edl", "错误板卡", "ABCDEF12")
    monkeypatch.setattr(strategy, "detect_device", lambda tool: device)
    calls = []
    def read_invalid(tool, directory, xml, **kwargs):
        calls.append(xml)
        (directory / "primary.bin").write_bytes(bytes(34 * 512))
        (directory / "backup.bin").write_bytes(bytes(33 * 512))
    monkeypatch.setattr(strategy, "_run", read_invalid)
    with pytest.raises(FlashError):
        strategy.pre_flash(Path("qdl"), target, config)
    assert [p.name for p in calls] == ["read-gpt.xml"]
    with pytest.raises(FlashError, match="尚未完成"):
        strategy._write(Path("qdl"), ["rootfs"], full=False)


def test_scope_cannot_expand_after_single_partition_preflight(monkeypatch, bundle):
    strategy, config, calls = prepared(monkeypatch, bundle, names={"rootfs"})
    with pytest.raises(FlashError, match="写入范围"):
        strategy._write(Path("qdl"), ["boot_a"], full=False)
    with pytest.raises(FlashError, match="写入范围"):
        strategy._write(Path("qdl"), ["rootfs"], full=True)
    assert len(calls) == 1
