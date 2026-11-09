"""普通临时目录模拟 configfs 自动属性和挂载；不操作真实设备或 /sys。"""
import pathlib
import subprocess

import pytest


@pytest.fixture
def gadget(tmp_path):
    """模拟 configfs 自动属性与命令；不证明实板 USB 枚举。"""
    source = (pathlib.Path(__file__).resolve().parents[1]
              / 'components/packages/arduino-unoq-runtime/usb/rootfs'
              / 'usr/lib/flange/unoq/adbd-usb-gadget').read_text()
    root = tmp_path
    mapping = {'/sys/kernel/config': str(root / 'config'), '/sys/class/udc': str(root / 'udc'),
               '/sys/firmware/devicetree/base/compatible': str(root / 'compatible'),
               '/sys/devices/soc0/serial_number': str(root / 'serial'),
               '/dev/usb-ffs/adb': str(root / 'ffs'), '/etc/hostname': str(root / 'hostname')}
    for old, new in mapping.items():
        source = source.replace(old, new)
    assert '/sys/' not in source and '/dev/' not in source
    (root / 'config/usb_gadget').mkdir(parents=True)
    (root / 'config/.mockmounted').touch()
    (root / 'udc/controller').mkdir(parents=True)
    (root / 'compatible').write_bytes(b'arduino,imola\0qcom,qrb2210\0')
    (root / 'serial').write_text('123456\n')
    (root / 'hostname').write_text('unoq\n')
    (root / 'uid').write_text('1000\n')
    log = root / 'commands'
    log.touch()
    helpers = '''
id() { cat "$MOCK_ROOT/uid"; }
echo() {
    if [[ $# == 1 && -z $1 ]]; then builtin echo unbind >> "$MOCK_LOG"; fi
    builtin echo "$@"
}
mountpoint() { [[ -f ${@: -1}/.mockmounted ]]; }
mount() {
    [[ ! -f $MOCK_ROOT/fail_mount ]] || return 1
    touch "${@: -1}/.mockmounted"
}
umount() { builtin echo umount >> "$MOCK_LOG"; /bin/rm "$1/.mockmounted"; }
mkdir() {
    /bin/mkdir "$@"
    if [[ -d $GADGET && ! -f $GADGET/UDC ]]; then touch "$GADGET/UDC"; fi
}
rm() { builtin echo "rm:$1" >> "$MOCK_LOG"; /bin/rm "$@"; }
rmdir() {
    builtin echo "rmdir:$1" >> "$MOCK_LOG"
    # configfs 属性及空的默认组会由内核随父目录删除；普通目录需在模拟器中移除。
    /usr/bin/find "$1" -maxdepth 1 -type f -delete
    local group
    for group in strings functions configs; do
        if [[ -d $1/$group ]]; then /bin/rmdir "$1/$group" 2>/dev/null || true; fi
    done
    /bin/rmdir "$1"
}
'''
    prefix = f'MOCK_ROOT={str(root)!r}\nMOCK_LOG={str(log)!r}\n'
    script = root / 'gadget'
    script.write_text(source.replace('set -xe', 'set -xe\n' + prefix + helpers, 1))
    def run(action, success=True):
        result = subprocess.run(['bash', str(script), action], text=True, capture_output=True)
        assert (result.returncode == 0) == success, result.stderr

    return root, log, run


def test_setup_activate_reset_are_idempotent_and_unbind_first(gadget):
    """重复操作不残留配置，解绑先于卸载及删除两种 USB 功能。"""
    root, log, run = gadget
    run('setup')
    run('setup')
    run('activate')
    run('activate')
    log.write_text('')
    run('reset')
    lines = log.read_text().splitlines()
    assert lines[:2] == ['unbind', 'umount'], lines
    for name in ['ffs.adb', 'acm.GS0']:
        assert next(i for i, line in enumerate(lines)
                    if line.endswith('/functions/' + name)) > 1
    assert not (root / 'config/usb_gadget/flange_unoq').exists()
    run('reset')
    assert log.read_text().splitlines() == lines


def test_partial_setup_failure_can_be_reset(gadget):
    """模拟 FunctionFS 挂载失败，已创建的 ACM 与 FFS 均能完整清理。"""
    root, _, run = gadget
    (root / 'fail_mount').touch()
    run('setup', False)
    assert (root / 'config/usb_gadget/flange_unoq/functions/acm.GS0').exists()
    run('reset')
    run('reset')
    assert not (root / 'config/usb_gadget/flange_unoq').exists()


@pytest.mark.parametrize('invalid', ['multiple_udc', 'missing_udc', 'board', 'uid'])
def test_invalid_identity_or_controller_is_rejected_without_creating_gadget(gadget, invalid):
    """身份与控制器错误必须在创建配置之前拒绝。"""
    root, log, run = gadget
    if invalid == 'multiple_udc':
        (root / 'udc/second').mkdir()
    elif invalid == 'missing_udc':
        (root / 'udc/controller').rmdir()
    elif invalid == 'board':
        (root / 'compatible').write_bytes(b'qcom,other\0')
    elif invalid == 'uid':
        (root / 'uid').write_text('1001\n')
    run('setup', False)
    assert not (root / 'config/usb_gadget/flange_unoq').exists()
    assert log.read_text() == ''
