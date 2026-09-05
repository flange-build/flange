"""当前平台输出契约必须完整覆盖各条真实构建路由。"""

from pathlib import Path

import pytest

from builder.component_plan import output_contract
from builder.workspace import Target, WorkspaceContext


def outputs(tmp_path, component, **config):
    ctx = WorkspaceContext(tmp_path, tmp_path, tmp_path / '.build', Target('board', 'default', 'release'))
    return {item.name: item for item in output_contract(component, config, ctx)}


def test_arm32_fit要求精确设备树模块与fit(tmp_path):
    specs = outputs(tmp_path, 'kernel', kernel={'image': 'zImage', 'boot_format': 'fit',
        'device_tree': {'directory': '', 'name': 'test'}})
    assert {spec.path.name for spec in specs.values()} == {'zImage', 'test.dtb', 'boot.img', 'modules'}
    assert specs['modules'].required and specs['modules'].kind == 'tree'


def test_ubi要求ubi镜像和软件包审计清单(tmp_path):
    specs = outputs(tmp_path, 'rootfs', rootfs={'image_format': 'ubi'})
    assert {spec.path.name for spec in specs.values()} == {'rootfs.ubi', 'packages.manifest'}


def test_mtd要求具名刷写清单参数与flash配置(tmp_path):
    specs = outputs(tmp_path, 'image', partitions={'format': 'mtd'})
    assert {spec.path.name for spec in specs.values()} == {'mtd-bundle.json', 'parameter.txt', 'flash-config.json'}


@pytest.mark.parametrize('platform,names', [
    ('rockchip', {'u-boot.itb', 'idbloader.img', 'miniloader.bin'}),
    ('amlogic', {'u-boot.bin', 'u-boot.bin.sd.bin'}),
    ('allwinnera733', {'boot0_sdcard.bin', 'boot0_ufs.bin', 'boot_package.fex'}),
    ('qualcommqcs6490', {'edk2-spi-firmware', 'prog_firehose_ddr.elf'}),
])
def test_各平台声明完整启动必需产物(tmp_path, platform, names):
    specs = outputs(tmp_path, 'bootloader', platform=platform, bootloader={'edk2_firmware': {'url': 'x'}})
    assert {item.path.name for item in specs.values()} == names
    assert all(item.required and not item.allow_empty for item in specs.values())


@pytest.mark.parametrize('format_,key', [('ext4', 'rootfs'), ('ubi', 'ubi')])
def test_Rockchip各路由保留软件包manifest产物(tmp_path, format_, key):
    from builder.platforms.rockchip.rootfs import RockchipRootfsBuilder
    builder = RockchipRootfsBuilder(None, None)
    builder._output = tmp_path / ('rootfs.ubi' if format_ == 'ubi' else 'rootfs.img')
    builder._packages_manifest = tmp_path / 'packages.manifest'
    result = builder.collect(None, {'rootfs': {'image_format': format_}})
    assert result == {key: builder._output, 'packages': builder._packages_manifest}
