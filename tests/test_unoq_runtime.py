"""UNO Q 固件、运行时固定输入与危险 MCU 操作的离线回归。"""

import importlib.util
import io
import hashlib
import json
from pathlib import Path
import runpy
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from builder.docker import BuildError
from builder.platforms.qualcommqrb2210.rootfs import kernel_release, USERDATA_UUID


PACKAGE = Path(__file__).resolve().parents[1] / 'components/packages/arduino-unoq-runtime'
SPEC = importlib.util.spec_from_file_location('unoq_prepare', PACKAGE / 'prepare.py')
PREPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREPARE)


class UnoQRuntimeTest(unittest.TestCase):
    def test_kernel_release_rejects_missing_or_ambiguous_modules(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(BuildError):
                kernel_release(root)
            (root / 'lib/modules/7.0.0-unoq').mkdir(parents=True)
            self.assertEqual(kernel_release(root), '7.0.0-unoq')
            (root / 'lib/modules/6.8.0').mkdir()
            with self.assertRaises(BuildError):
                kernel_release(root)

    def test_download_rejects_tampered_cache_and_bad_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                PREPARE.download({'sha256': 'placeholder', 'url': 'https://example.com'}, Path(directory))

    def test_archive_blocks_path_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'escape.tar'
            with tarfile.open(archive, 'w') as output:
                entry = tarfile.TarInfo('../../outside')
                output.addfile(entry)
            with self.assertRaises(tarfile.FilterError):
                PREPARE.unpack_archive(archive, Path(directory) / 'dest')

    def test_safe_destination_rejects_symlink_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'outside').symlink_to('/tmp')
            with self.assertRaises(ValueError):
                PREPARE.safe_destination(root, 'outside/wrong')
            with self.assertRaises(ValueError):
                PREPARE.safe_destination(root, '../wrong')

    def test_gpio_v1_v2_commands_and_unknown_pin(self):
        gpio = runpy.run_path(str(PACKAGE / 'rootfs/usr/lib/flange/unoq/gpio'))
        command = gpio['command']
        self.assertEqual(command('gpioset (libgpiod) v1.6.3', '70=1'),
                         ['gpioset', '--mode=exit', 'gpiochip1', '70=1'])
        self.assertEqual(command('gpioset (libgpiod) v2.2', '70=1')[-1], '70=1')
        with self.assertRaises(ValueError):
            command('v3.0', '70=1')
        with self.assertRaises(ValueError):
            command('v1.6.3', '999=1')

    def test_locked_inputs_and_no_debian_kernel_metapackage(self):
        resources = json.loads((PACKAGE / 'resources.lock.json').read_text())['resources']
        names = {r['name'] for r in resources}
        self.assertTrue({'arduino-cli', 'arduino-app-cli', 'arduino-app-lab',
                         'arduino-router', 'zephyr-core', 'remoteocd',
                         'Arduino_RouterBridge', 'Arduino_RPClite'} <= names)
        self.assertNotIn('arduino-unoq', names)
        for resource in resources:
            self.assertRegex(resource['sha256'], r'^[a-f0-9]{64}$')
            self.assertTrue(resource['url'].startswith('https://'))
        images = json.loads((PACKAGE / 'containers.lock.json').read_text())['images']
        self.assertGreaterEqual(len(images), 3)
        for image in images:
            self.assertRegex(image['image'], r'@sha256:[a-f0-9]{64}$')
            self.assertRegex(image['config_digest'], r'^sha256:[a-f0-9]{64}$')

    def test_boot_slot_requires_truth_and_rejects_conflicts(self):
        code = runpy.run_path(str(PACKAGE / 'rootfs/usr/lib/flange/unoq/mark-boot-success'))
        slot = code['boot_slot']
        self.assertEqual(slot('root=LABEL=rootfs', b'_b\0'), 'b')
        self.assertEqual(slot('androidboot.slot_suffix=_a'), 'a')
        for cmdline, chosen in [('', None), ('slot_suffix=_c', None),
                                ('slot_suffix=_a slot_suffix=_a', None),
                                ('slot_suffix=_a', b'_b\0'), ('', b'_a')]:
            with self.assertRaises(ValueError):
                slot(cmdline, chosen)

    def test_mcu_initialization_is_explicit_and_idempotent(self):
        script = str(PACKAGE / 'rootfs/usr/lib/flange/unoq/mcu-initialize')
        with tempfile.TemporaryDirectory() as directory:
            with patch('pathlib.Path.home', return_value=Path(directory)), \
                 patch('pathlib.Path.read_bytes', return_value=b'arduino,imola\0'), \
                 patch('os.getuid', return_value=1000), \
                 patch('subprocess.run') as command, \
                 patch('sys.argv', [script, '--replace-mcu-firmware']):
                runpy.run_path(script)
                command.assert_called_once()
                with self.assertRaises(SystemExit) as result:
                    runpy.run_path(script)
                self.assertEqual(result.exception.code, 0)
                command.assert_called_once()
                with patch('sys.argv', [script, '--replace-mcu-firmware', '--force']):
                    runpy.run_path(script)
                self.assertEqual(command.call_count, 2)

    def test_userdata_resize_requires_exact_mount(self):
        parse = runpy.run_path(str(PACKAGE / 'rootfs/usr/lib/flange/unoq/grow-userdata'))['mount_source']
        self.assertEqual(parse('/dev/mmcblk0p42 ext4 ' + USERDATA_UUID), '/dev/mmcblk0p42')
        for output in ['', '/dev/mmcblk0p42 ext4 wrong-uuid',
                       '/dev/sda1 ext4 ' + USERDATA_UUID,
                       '/dev/mmcblk0p42 vfat ' + USERDATA_UUID]:
            with self.assertRaises(ValueError):
                parse(output)

    def test_models_rejects_changed_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'usr/share/flange/unoq').mkdir(parents=True)
            name = 'models/ootb/ei/test.eim'
            content = '固定模型测试数据'.encode()
            layer_data = io.BytesIO()
            with tarfile.open(fileobj=layer_data, mode='w') as layer:
                member = tarfile.TarInfo(name)
                member.size = len(content)
                layer.addfile(member, io.BytesIO(content))
            archive = root / 'image.tar.gz'
            with tarfile.open(archive, 'w:gz') as outer:
                member = tarfile.TarInfo('flat-layer.tar')
                member.size = len(layer_data.getvalue())
                outer.addfile(member, io.BytesIO(layer_data.getvalue()))
            expected = {name: {'sha256': hashlib.sha256(content).hexdigest(), 'size': len(content)}}
            lock = root / 'models.lock.json'
            lock.write_text(json.dumps(expected))
            with patch.object(PREPARE, 'HERE', root):
                PREPARE.verify_models(archive, root)
                expected[name]['sha256'] = '0' * 64
                lock.write_text(json.dumps(expected))
                with self.assertRaises(ValueError):
                    PREPARE.verify_models(archive, root)

    def test_compose_consumes_locked_image(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / 'home/arduino/.local/share/arduino-app-cli/assets/0.12.0'
            assets.mkdir(parents=True)
            (root / 'usr/share/flange/unoq').mkdir(parents=True)
            (root / 'optional-models.lock.json').write_text('[]')
            (assets / 'models-list.yaml').write_text('[]')
            compose = assets / 'brick_compose.yaml'
            compose.write_text('services:\n  model:\n    image: ${REGISTRY:-example/}runner:1.0\n')
            image = 'example/runner@sha256:' + 'a' * 64
            with patch.object(PREPARE, 'HERE', root):
                PREPARE.lock_compose(root, {'images': [{'tag': 'example/runner:1.0', 'image': image}]})
            self.assertIn('image: ' + image, compose.read_text())

    def test_ucm_preserves_ubuntu_shared_macros(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ucm = root / 'usr/share/alsa/ucm2'
            (ucm / 'codecs/qcom-lpass').mkdir(parents=True)
            (ucm / 'codecs/qcom-lpass/enable.conf').write_text('EnableSequence []')
            board = ucm / 'Qualcomm/qcm2290'
            board.mkdir(parents=True)
            (board / 'Headphones.conf').write_text('Include.test.File "/codecs/qcom-lpass/enable.conf"')
            PREPARE.privatize_ucm(root)
            self.assertFalse((ucm / 'codecs').exists())
            self.assertTrue((board / 'codecs/qcom-lpass/enable.conf').is_file())
            self.assertIn('/Qualcomm/qcm2290/codecs/', (board / 'Headphones.conf').read_text())

    def test_no_automatic_mcu_initialization_unit(self):
        units = PACKAGE / 'rootfs/etc/systemd/system'
        self.assertFalse(any('burn-bootloader' in p.read_text() for p in units.glob('*.service')))
        self.assertEqual(USERDATA_UUID, '66f6d9a8-6ce3-46f6-b679-a1a1d991ba19')


if __name__ == '__main__':
    unittest.main()
