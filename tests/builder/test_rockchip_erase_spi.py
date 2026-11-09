"""SPI 独立擦除：目标介质隔离、命令顺序与失败中止。"""

import subprocess
from unittest.mock import patch

import pytest

from builder.flash.execute import FlashExecutor, _cli_main
from builder.flash.model import FlashConfig, FlashError, PreFlashConfig
from builder.presentation import UsageError


@pytest.fixture
def target(tmp_path):
    loader = tmp_path / 'bootloader' / 'miniloader.bin'
    loader.parent.mkdir()
    loader.write_bytes(b'loader')
    config = FlashConfig(
        platform='rockchip', flash_tool='upgrade_tool', board='radxa-rock5b',
        product='default', variant='debug', soc='rk3588', storage='EMMC',
        pre_flash=PreFlashConfig(download_boot='bootloader/miniloader.bin'),
    )
    config.to_json(tmp_path / 'flash-config.json')
    return tmp_path


def run_erase(target, *, mode='Maskrom', no_wait=False, no_reboot=False,
              fail=None, chip='RK3588', active=True, listing_returncode=0,
              fail_switch=False, empty_confirmation=False):
    calls = []
    listing_count = 0

    def run(cmd, **kwargs):
        nonlocal listing_count
        args = cmd[1:]
        calls.append(args)
        stdout = ''
        code = 0
        if args == ['LD']:
            count = 1 + mode.count('DevNo=')
            stdout = f'List of rockusb connected({count})\nDevNo=1 {mode}'
        elif args == ['RCI']:
            stdout = chip
        elif args == ['SSD']:
            listing_count += 1
            selected = active and listing_count > 1
            stdout = 'No=2 EMMC\nNo=5 SPINOR' + ('(*)' if selected else '') + '\n'
            code = listing_returncode
            if empty_confirmation and listing_count > 1:
                stdout = ''
        if fail_switch and args == ['SSD', '5']:
            code = 1
        if fail == args[0]:
            code = 1
            stdout = ''
        if code and kwargs.get('check'):
            raise subprocess.CalledProcessError(code, cmd)
        return subprocess.CompletedProcess(cmd, code, stdout, '')

    executor = FlashExecutor(target)
    with patch('builder.flash.strategy.subprocess.run', side_effect=run), \
            patch('builder.flash.strategy.time.sleep'), \
            patch.object(executor.strategy, 'find_tool', return_value='upgrade_tool'):
        try:
            executor.erase_spi(no_wait=no_wait, no_reboot=no_reboot)
        except Exception as error:
            return calls, error
    return calls, None


@pytest.mark.parametrize('no_wait', [False, True])
@pytest.mark.parametrize('mode', ['Maskrom', 'Loader'])
def test_erase_sequence(target, mode, no_wait):
    calls, error = run_erase(target, mode=mode, no_wait=no_wait)
    assert error is None
    loader = str(target / 'bootloader/miniloader.bin')
    expected = [['LD']]
    if mode == 'Maskrom':
        expected.append(['DB', loader])
    expected += [['RCI'], ['SSD'], ['SSD', '5'], ['SSD'], ['EF', loader]]
    assert calls == expected


@pytest.mark.parametrize('fail', ['DB', 'RCI', 'SSD', 'EF'])
def test_command_failure_stops_erase(target, fail, capsys):
    calls, error = run_erase(target, fail=fail)
    assert error is not None
    assert calls[-1][0] == fail
    assert ['RD'] not in calls
    assert 'SPI NOR 擦除完成' not in capsys.readouterr().out


def test_nonzero_quit_status_accepts_valid_storage_lists(target):
    """两次列表查询输入 Q 后都返回非零值，仍按列表内容选择并确认 SPI。"""
    calls, error = run_erase(target, listing_returncode=1)
    assert error is None
    assert ['SSD', '5'] in calls
    assert calls[-1] == ['EF', str(target / 'bootloader/miniloader.bin')]
    assert ['RD'] not in calls


@pytest.mark.parametrize('kwargs', [
    {'active': False}, {'empty_confirmation': True}, {'fail_switch': True},
])
def test_nonzero_quit_status_does_not_bypass_spi_confirmation(target, kwargs):
    calls, error = run_erase(target, listing_returncode=1, **kwargs)
    assert error is not None
    assert not any(cmd[0] in {'EF', 'RD'} for cmd in calls)


@pytest.mark.parametrize('kwargs', [
    {'chip': 'RK3566'}, {'active': False}, {'mode': ''},
    {'mode': 'Loader\nDevNo=2 Maskrom'},
])
def test_unsafe_device_never_erased(target, kwargs):
    calls, error = run_erase(target, no_wait=True, **kwargs)
    assert isinstance(error, FlashError)
    assert not any(cmd[0] in {'EF', 'RD', 'WL', 'UL', 'DI'} for cmd in calls)


def test_loader_required_before_usb(target):
    (target / 'bootloader/miniloader.bin').unlink()
    with patch('builder.flash.strategy.subprocess.run') as run:
        with pytest.raises(FlashError, match='miniloader'):
            FlashExecutor(target).erase_spi()
    run.assert_not_called()


def test_other_platform_rejected_before_usb(target):
    config = FlashConfig.from_json(target / 'flash-config.json')
    config.platform = 'amlogic'
    config.to_json(target / 'flash-config.json')
    with patch('builder.flash.strategy.subprocess.run') as run:
        with pytest.raises(FlashError, match='不支持 --erase-spi'):
            FlashExecutor(target).erase_spi()
    run.assert_not_called()


@pytest.mark.parametrize('option', [
    ['boot'], ['--raw', '/dev/sdx'], ['--list'], ['--spi-firmware'], ['--provision-ufs'],
])
def test_cli_rejects_conflicting_operation_before_executor(target, option):
    with patch('builder.flash.execute.FlashExecutor') as executor:
        with pytest.raises(UsageError, match='不能与'):
            _cli_main(['--erase-spi', *option], public=True, target_dir=target,
                      project_dir=target)
    executor.assert_not_called()


@pytest.mark.parametrize('public', [True, False])
def test_cli_dispatches_erase(target, public):
    argv = ['--erase-spi', '--no-wait']
    if not public:
        argv = ['run', '--target-dir', str(target), *argv]
    with patch.object(FlashExecutor, 'erase_spi') as erase, \
            patch.object(FlashExecutor, 'flash_all') as flash:
        _cli_main(argv, public=public, target_dir=target, project_dir=target)
    erase.assert_called_once_with(no_wait=True, no_reboot=False)
    flash.assert_not_called()


def test_default_flash_does_not_erase(target):
    with patch.object(FlashExecutor, 'erase_spi') as erase, \
            patch.object(FlashExecutor, 'flash_all') as flash:
        _cli_main([], public=True, target_dir=target, project_dir=target)
    flash.assert_called_once_with(no_wait=False, no_reboot=False, yes=False)
    erase.assert_not_called()


def test_erase_success_does_not_reset_twice(target, capsys):
    """实机 EF 成功后已复位，任何后续 RD 都会失败。"""
    calls, error = run_erase(target, fail='RD')
    assert error is None
    assert calls[-1][0] == 'EF'
    assert 'SPI NOR 擦除完成' in capsys.readouterr().out


@pytest.mark.parametrize('no_wait', [False, True])
def test_no_reboot_rejected_before_device_access(target, no_wait):
    calls, error = run_erase(target, no_wait=no_wait, no_reboot=True)
    assert isinstance(error, FlashError)
    assert '不支持 --no-reboot' in str(error)
    assert calls == []
