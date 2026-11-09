#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""独立初始化 Radxa Dragon Q8B 的 UFS（通用闪存存储）；仅依赖 Python 标准库。"""

import argparse
import ctypes
import ctypes.util
import hashlib
from pathlib import Path
import platform
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile


TOOL_URL = 'https://dl.radxa.com/dragon/q6a/images/edl-ng-dist-v1.6.0.zip'
TOOL_SHA256 = 'dc062b6c70839ee97d1fa69a93af4df0fd4ceefe2c33d789bb9cda264d7b4571'
FIRMWARE_BASE = (
    'https://raw.githubusercontent.com/armbian/qcombin/'
    'f2d55c46dcbe2af57dc400658cd14e70cd8baa79/Makena/'
)
LOADER = (
    'prog_firehose_ufs.elf', FIRMWARE_BASE + 'prog_firehose_ddr.elf',
    '2922271fb6d0792d737fb757e7783513b2e7ca54eacb219e80e58ba233dcbaf2',
)
PROFILES = {
    'lun0-only': (
        'provision_ufs31_lun0_only.xml',
        FIRMWARE_BASE + 'radxa-dragon-q8b/provision_ufs31_lun0_only.xml',
        '54709fd22904972066ab3bbae58e65da9cda404fdfdacac2cae83feca98ac5c8',
    ),
    'qcom': (
        'provision_ufs31.xml',
        'https://dl.radxa.com/q6a/images/android/provision_ufs31.xml',
        '2eca74731049bfb399ec88bdbb830b5163910c471902d15dc3bfa6e9c1889c3e',
    ),
}


def digest(path: Path) -> str:
    """流式计算 SHA-256（内容摘要）。"""
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fetch(cache: Path, name: str, url: str, sha256: str, offline: bool) -> Path:
    """缓存与下载均须校验；临时下载完整后原子发布。"""
    destination = cache / name
    if destination.is_file() and digest(destination) == sha256:
        print(f'已校验：{name}', flush=True)
        return destination
    if offline:
        raise RuntimeError(f'离线缓存缺失或校验失败：{destination}；请先联网运行 --prepare-only')
    print(f'下载：{url}', flush=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=cache, delete=False) as output:
            temporary = Path(output.name)
            request = urllib.request.Request(url, headers={'User-Agent': 'q8b-ufs-provision/1'})
            with urllib.request.urlopen(request, timeout=60) as response:
                shutil.copyfileobj(response, output)
        if digest(temporary) != sha256:
            raise RuntimeError(f'SHA-256 校验失败：{name}；不会使用该文件')
        temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination


def host_target() -> str:
    """按宿主系统和架构选择官方预编译工具，不依赖仓库或 PATH 中的 edl-ng。"""
    system = {'Linux': 'linux', 'Darwin': 'macos'}.get(platform.system())
    arch = {'x86_64': 'x64', 'amd64': 'x64', 'arm64': 'arm64',
            'aarch64': 'arm64'}.get(platform.machine().lower())
    if not system or not arch:
        raise RuntimeError('仅支持 Linux / macOS 的 x86_64 和 ARM64 宿主机')
    return f'{system}-{arch}'


def extract_tool(archive: Path, directory: Path, target: str) -> Path:
    """只提取当前平台的确定文件，每次从已校验的压缩包重新提取。"""
    names = ['edl-ng', 'LICENSE', 'README.md']
    if target.startswith('macos-'):
        names.append('libusb-1.0.dylib')
    with zipfile.ZipFile(archive) as bundle:
        for name in names:
            with bundle.open(f'edl-ng-{target}/{name}') as source:
                with (directory / name).open('wb') as output:
                    shutil.copyfileobj(source, output)
    tool = directory / 'edl-ng'
    tool.chmod(0o700)
    return tool


def edl_devices() -> list[str]:
    """被动枚举 EDL（紧急下载模式）USB 9008；不提前打开 Sahara 会话。"""
    devices = []
    if platform.system() == 'Linux':
        for device in sorted(Path('/sys/bus/usb/devices').glob('*')):
            try:
                vid = (device / 'idVendor').read_text().strip().lower()
                pid = (device / 'idProduct').read_text().strip().lower()
            except FileNotFoundError:
                continue
            if (vid, pid) == ('05c6', '9008'):
                devices.append(device.name)
    else:
        result = subprocess.run(
            ['ioreg', '-a', '-p', 'IOUSB', '-l'], check=True,
            capture_output=True, timeout=10,
        )

        def visit(node: object) -> None:
            if isinstance(node, list):
                for child in node:
                    visit(child)
            elif isinstance(node, dict):
                if node.get('idVendor') == 0x05C6 and node.get('idProduct') == 0x9008:
                    devices.append(str(node.get('locationID', '9008')))
                visit(node.get('IORegistryEntryChildren', []))

        visit(plistlib.loads(result.stdout))
    return devices


def require_one_device() -> None:
    devices = edl_devices()
    if len(devices) != 1:
        raise RuntimeError(
            f'检测到 {len(devices)} 块 EDL 9008 设备；请只连接一块 Q8B 并使其进入 EDL 模式'
        )
    print(f'检测到 EDL 9008：{devices[0]}（USB 标识不能验证板卡型号）', flush=True)


def check_runtime(tool: Path) -> None:
    """仅检查本机运行库和命令帮助，不接触设备。"""
    if platform.system() == 'Linux':
        library = ctypes.util.find_library('usb-1.0')
        if not library:
            raise RuntimeError('缺少 libusb；Debian/Ubuntu 请运行 sudo apt install libusb-1.0-0')
        ctypes.CDLL(library)
    result = subprocess.run(
        [str(tool), 'provision', '--help'], capture_output=True, text=True, timeout=30,
    )
    if result.returncode or 'xmlfile' not in result.stdout:
        raise RuntimeError(f'edl-ng 运行检查失败：\n{result.stdout}\n{result.stderr}')


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description='独立对 Radxa Dragon Q8B 执行 UFS provision（存储布局初始化）。',
        epilog='首次运行需联网。初始化可能清除数据；仅用于 Q8B，不自动刷写系统或 SPI。',
    )
    result.add_argument('--profile', choices=PROFILES, default='lun0-only',
                        help='lun0-only：单用户 LUN（逻辑单元，默认）；qcom：官方 LUN 0–7')
    result.add_argument('--cache-dir', type=Path,
                        default=Path.home() / '.cache' / 'q8b-ufs-provision',
                        help='下载缓存目录，可复制给其他用户供离线使用')
    result.add_argument('--offline', action='store_true', help='仅使用已校验的缓存，禁止下载')
    mode = result.add_mutually_exclusive_group()
    mode.add_argument('--prepare-only', action='store_true', help='只准备资源并检查宿主运行环境')
    mode.add_argument('--dry-run', action='store_true', help='准备资源并显示命令，不连接设备')
    result.add_argument('-y', '--yes', action='store_true', help='明确确认 Q8B 型号及数据风险，免交互')
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if sys.version_info < (3, 12):
        raise RuntimeError('请使用 Python 3.12 或更高版本；无需安装 pip 包')
    target = host_target()
    cache = args.cache_dir.expanduser().resolve()
    cache.mkdir(parents=True, exist_ok=True)
    archive = fetch(cache, 'edl-ng-dist-v1.6.0.zip', TOOL_URL, TOOL_SHA256, args.offline)
    loader = fetch(cache, *LOADER, args.offline)
    provision = fetch(cache, *PROFILES[args.profile], args.offline)
    # 使用独立临时执行目录，避免并发覆盖工具文件；离线仅保留经过校验的原始资源。
    with tempfile.TemporaryDirectory(prefix='q8b-provision-') as temporary:
        directory = Path(temporary)
        tool = extract_tool(archive, directory, target)
        check_runtime(tool)
        if args.prepare_only:
            print(f'资源与宿主环境检查通过；布局：{args.profile}；缓存：{cache}')
            return 0
        # 将固件复制到本次执行目录，防止其他进程刷新缓存时改变本次输入。
        for asset in (loader, provision):
            shutil.copyfile(asset, directory / asset.name)
        loader = directory / loader.name
        provision = directory / provision.name
        for asset, expected in ((loader, LOADER[2]), (provision, PROFILES[args.profile][2])):
            if digest(asset) != expected:
                raise RuntimeError(f'执行前资源校验失败：{asset.name}')
        command = [str(tool), '--loader', str(loader), '--memory', 'UFS',
                   'provision', str(provision)]
        print(f'Q8B / {args.profile}：{shlex.join(command)}', flush=True)
        if args.dry_run:
            print('预览完成，未连接设备；上述临时路径将在退出时清理。')
            return 0
        require_one_device()
        print('即将初始化 Q8B UFS，可能清除全部数据或受已有配置锁限制。', flush=True)
        if not args.yes:
            if not sys.stdin.isatty():
                raise RuntimeError('非交互执行必须显式提供 --yes')
            if input('确认唯一连接的是 Q8B 且允许初始化，请输入 Q8B：').strip() != 'Q8B':
                print('已取消，未执行 provision。')
                return 1
        require_one_device()
        status = subprocess.run(command, cwd=directory).returncode
        if status:
            print(f'provision 失败（edl-ng 退出码 {status}）；请查看上方原始错误。', file=sys.stderr)
            return status if status > 0 else 1
        print('UFS provision 完成。请断电后重新进入 EDL，再用你的刷写工具写入系统镜像。')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\n已中断；若 provision 已开始，设备可能已部分修改，请检查后再操作。', file=sys.stderr)
        sys.exit(130)
    except (OSError, RuntimeError, ValueError, EOFError, subprocess.SubprocessError,
            zipfile.BadZipFile, KeyError) as error:
        print(f'错误：{error}', file=sys.stderr)
        sys.exit(1)
