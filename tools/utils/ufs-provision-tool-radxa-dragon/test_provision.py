"""独立脚本回归测试：不联网，不连接或修改真实设备。"""

import contextlib
import hashlib
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile


SPEC = importlib.util.spec_from_file_location('provision', Path(__file__).with_name('provision.py'))
provision = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provision)


class ProvisionTests(unittest.TestCase):
    """验证不可逆入口与独立资源准备的边界。"""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.cache = Path(self.temporary.name)

    def test_download_and_offline_integrity(self) -> None:
        payload = b'known firmware'
        checksum = hashlib.sha256(payload).hexdigest()
        with patch.object(provision.urllib.request, 'urlopen', return_value=io.BytesIO(payload)):
            result = provision.fetch(
                self.cache, 'loader', 'https://example.org/loader', checksum, False,
            )
        with patch.object(provision.urllib.request, 'urlopen') as download:
            self.assertEqual(provision.fetch(self.cache, 'loader', '', checksum, True), result)
            download.assert_not_called()
            result.write_bytes(b'corrupt')
            with self.assertRaisesRegex(RuntimeError, '校验失败'):
                provision.fetch(self.cache, 'loader', '', checksum, True)
            with self.assertRaisesRegex(RuntimeError, '缺失'):
                provision.fetch(self.cache, 'missing', '', checksum, True)

    def test_failed_download_does_not_publish(self) -> None:
        target = self.cache / 'loader'
        target.write_bytes(b'old')
        with patch.object(provision.urllib.request, 'urlopen', return_value=io.BytesIO(b'wrong')):
            with self.assertRaisesRegex(RuntimeError, 'SHA-256'):
                provision.fetch(self.cache, 'loader', 'https://example.org/loader', '0' * 64, False)
        self.assertEqual(target.read_bytes(), b'old')
        self.assertEqual(list(self.cache.iterdir()), [target])

    def test_device_count_guard(self) -> None:
        for devices in ([], ['one', 'two']):
            with self.subTest(devices=devices), patch.object(
                provision, 'edl_devices', return_value=devices,
            ):
                with self.assertRaises(RuntimeError):
                    provision.require_one_device()
        with patch.object(provision, 'edl_devices', return_value=['one']):
            provision.require_one_device()

    def test_macos_requires_vid_and_pid_on_same_device(self) -> None:
        tree = [{'idVendor': 0x05C6, 'idProduct': 1},
                {'idVendor': 1, 'idProduct': 0x9008}]
        with patch.object(provision.platform, 'system', return_value='Darwin'):
            with patch.object(provision.subprocess, 'run') as run:
                run.return_value.stdout = provision.plistlib.dumps(tree)
                self.assertEqual(provision.edl_devices(), [])
                tree.append({'IORegistryEntryChildren': [
                    {'idVendor': 0x05C6, 'idProduct': 0x9008, 'locationID': 123}]})
                run.return_value.stdout = provision.plistlib.dumps(tree)
                self.assertEqual(provision.edl_devices(), ['123'])

    def test_execution_modes_and_failure_status(self) -> None:
        loader = self.cache / 'loader.elf'
        layout = self.cache / 'layout.xml'
        loader.write_bytes(b'loader')
        layout.write_bytes(b'xml')
        archive = self.cache / 'tool.zip'
        with zipfile.ZipFile(archive, 'w') as bundle:
            for name in ('edl-ng', 'LICENSE', 'README.md'):
                bundle.writestr(f'edl-ng-linux-x64/{name}', b'test')
        modes = [(['--dry-run'], 0, False), (['--prepare-only'], 0, False),
                 (['--yes'], 0, True), (['--yes'], 7, True),
                 ([], 1, False)]
        for flags, status, should_run in modes:
            with self.subTest(flags=flags, status=status), contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(
                    provision, 'host_target', return_value='linux-x64',
                ))
                stack.enter_context(patch.object(provision, 'check_runtime'))
                stack.enter_context(patch.object(
                    provision, 'fetch', side_effect=[archive, loader, layout],
                ))
                stack.enter_context(patch.object(
                    provision, 'LOADER', ('loader.elf', '', provision.digest(loader)),
                ))
                stack.enter_context(patch.object(provision, 'PROFILES', {
                    'lun0-only': ('layout.xml', '', provision.digest(layout)),
                }))
                detect = stack.enter_context(patch.object(provision, 'require_one_device'))
                run = stack.enter_context(patch.object(
                    provision.subprocess, 'run',
                    return_value=subprocess.CompletedProcess([], status),
                ))
                stack.enter_context(patch.object(provision.sys.stdin, 'isatty', return_value=True))
                stack.enter_context(patch('builtins.input', return_value='cancel'))
                result = provision.main(['--cache-dir', str(self.cache), *flags])
                self.assertEqual(result, status)
                if should_run:
                    command = run.call_args.args[0]
                    self.assertEqual(command[1], '--loader')
                    self.assertEqual(command[3:6], ['--memory', 'UFS', 'provision'])
                    self.assertEqual(Path(command[2]).name, 'loader.elf')
                    self.assertEqual(Path(command[6]).name, 'layout.xml')
                    self.assertEqual(detect.call_count, 2)
                else:
                    run.assert_not_called()
                    if flags:
                        detect.assert_not_called()
                    else:
                        detect.assert_called_once()


if __name__ == '__main__':
    unittest.main()
