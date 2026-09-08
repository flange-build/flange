#!/usr/bin/env python3
"""在构建容器校验固定资源，提取内容，交由 flange 重新生成自有 DEB。

不安装上游 DEB，不运行其维护脚本，不携带 Debian 动态系统库。
"""

import gzip
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile


HERE = Path(__file__).resolve().parent


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def download(resource, cache):
    expected = resource['sha256']
    if len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected):
        raise ValueError('资源必须声明真实 SHA256')
    if not resource['url'].startswith('https://'):
        raise ValueError('资源下载必须使用 HTTPS')
    cache.mkdir(parents=True, exist_ok=True)
    output = cache / expected
    if output.exists() and digest(output) == expected:
        return output
    pending = output.with_suffix('.partial')
    try:
        with urllib.request.urlopen(resource['url'], timeout=120) as source, pending.open('wb') as dest:
            shutil.copyfileobj(source, dest)
        if digest(pending) != expected:
            raise ValueError(f"资源摘要不匹配：{resource['name']}")
        pending.replace(output)
    finally:
        pending.unlink(missing_ok=True)
    return output


def safe_destination(root, relative):
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError(f'不安全安装路径：{relative}')
    destination = root / path
    if not destination.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'安装路径穿过符号链接：{relative}')
    return destination


def unpack_archive(archive, destination, zipped=False):
    """Arduino 格式剥掉唯一顶层目录；保留真实权限，拒绝越界成员。"""
    with tempfile.TemporaryDirectory() as temporary:
        staging = Path(temporary)
        if zipped:
            with zipfile.ZipFile(archive) as src:
                for entry in src.infolist():
                    safe_destination(staging, entry.filename)
                src.extractall(staging)
        else:
            with tarfile.open(archive) as src:
                src.extractall(staging, filter='data')
        children = list(staging.iterdir())
        source = children[0] if len(children) == 1 and children[0].is_dir() else staging
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination, dirs_exist_ok=True, symlinks=True)


def install_firmware(source, dest):
    """补充固件使用 updates 优先目录，不覆盖 Ubuntu linux-firmware 包。"""
    firmware = source / 'usr/lib/firmware'
    if not firmware.is_dir():
        firmware = source / 'lib/firmware'
    wanted = ['qcom/qcm2290', 'qcom/a702_sqe.fw', 'ath10k/WCN3990', 'qca']
    for relative in wanted:
        path = firmware / relative
        if not path.exists():
            continue
        target = dest / 'usr/lib/firmware/updates' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.is_dir():
            # 同时移动完整相对布局；跨 firmware 包别名稍后由其它资源补齐。
            shutil.copytree(path, target, dirs_exist_ok=True, symlinks=True)
        else:
            shutil.copy2(path, target)
    docs = source / 'usr/share/doc'
    if docs.is_dir():
        shutil.copytree(docs, dest / 'usr/share/doc/flange-arduino-unoq-runtime/upstream',
                        dirs_exist_ok=True, symlinks=True)


def install_resource(resource, cache, dest):
    archive = download(resource, cache)
    kind = resource['kind']
    if kind == 'libgpiod-source':
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            unpack_archive(archive, source)
            subprocess.run([str(source / 'configure'), '--host=aarch64-linux-gnu',
                            '--prefix=/opt/arduino', '--disable-tools', '--disable-tests',
                            '--disable-bindings-cxx', '--disable-bindings-python',
                            '--disable-bindings-rust'], cwd=source, check=True)
            subprocess.run(['make', '-j2'], cwd=source, check=True)
            subprocess.run(['make', 'install', 'DESTDIR=' + str(dest)], cwd=source, check=True)
            docs = dest / 'usr/share/doc/flange-arduino-unoq-runtime/libgpiod'
            docs.mkdir(parents=True, exist_ok=True)
            for name in ['COPYING', 'LICENSES/LGPL-2.1-or-later.txt']:
                license_file = source / name
                if license_file.is_file():
                    shutil.copy2(license_file, docs / license_file.name)
        return
    if kind == 'qbootctl-source':
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            unpack_archive(archive, source)
            binary = dest / 'usr/bin/qbootctl'
            binary.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run([os.environ.get('CC', 'aarch64-linux-gnu-gcc'), '-O2', '-std=gnu11',
                            '-o', str(binary), *[str(source / name) for name in
                            ['qbootctl.c', 'bootctrl_impl.c', 'gpt-utils.c', 'ufs-bsg.c', 'crc32.c']]],
                           check=True)
            docs = dest / 'usr/share/doc/flange-arduino-unoq-runtime/qbootctl-source'
            shutil.copytree(source, docs, dirs_exist_ok=True)
        return
    if kind in ('deb', 'firmware-deb'):
        with tempfile.TemporaryDirectory() as temporary:
            tree = Path(temporary)
            subprocess.run(['dpkg-deb', '--extract', str(archive), str(tree)], check=True)
            if kind == 'firmware-deb':
                install_firmware(tree, dest)
            else:
                # 上游 kernel 元包与系统库不在白名单；维护脚本由本包重建。
                shutil.copytree(tree, dest, dirs_exist_ok=True, symlinks=True)
        return
    target = safe_destination(dest, resource['destination'])
    if kind in ('arduino-archive', 'library-zip'):
        unpack_archive(archive, target, kind == 'library-zip')
    elif kind == 'file':
        target.parent.mkdir(parents=True, exist_ok=True)
        if resource.get('symlink'):
            link = archive.read_text().strip()
            if Path(link).is_absolute() or not (target.parent / link).resolve().is_relative_to(dest.resolve()):
                raise ValueError('上游 overlay 符号链接越界')
            target.unlink(missing_ok=True)
            target.symlink_to(link)
            return
        shutil.copyfile(archive, target)
        target.chmod(0o755 if resource.get('executable') else 0o644)
    else:
        raise ValueError(f'未知资源类型：{kind}')


def verify_models(archive, dest):
    """从固定 OCI 归档核验实际模型字节，兼容扁平和目录式 layer 名称。"""
    expected = json.loads((HERE / 'models.lock.json').read_text())
    found = {}
    with tarfile.open(archive, mode='r|gz') as outer:
        for member in outer:
            if not member.isfile() or not member.name.endswith('.tar'):
                continue
            with tarfile.open(fileobj=outer.extractfile(member), mode='r|') as layer:
                for item in layer:
                    name = item.name.removeprefix('./')
                    if item.isfile() and name.startswith('models/ootb/ei/'):
                        found[name] = {
                            'sha256': hashlib.file_digest(layer.extractfile(item), 'sha256').hexdigest(),
                            'size': item.size,
                        }
    if found != expected:
        raise ValueError('EI 内置模型与固定清单不符')
    (dest / 'usr/share/flange/unoq/models.manifest.json').write_text(
        json.dumps(found, indent=2) + '\n')


def prepare_image(item, cache, dest):
    if '@sha256:' not in item['image']:
        raise ValueError('容器必须固定 manifest 摘要')
    name = item['tag'].split('/')[-1].replace(':', '-') + '.tar.gz'
    item['archive'] = name
    target = cache / name
    subprocess.run(['skopeo', 'copy', '--override-arch', 'arm64', '--override-os', 'linux',
                    'docker://' + item['image'],
                    'docker-archive:' + str(target.with_suffix('')) + ':' + item['tag']], check=True)
    raw = target.with_suffix('')
    with raw.open('rb') as source, gzip.open(target, 'wb', compresslevel=1) as output:
        shutil.copyfileobj(source, output)
    raw.unlink()
    if item['tag'].split('/')[-1].startswith('ei-models-runner:'):
        verify_models(target, dest)
    target.with_suffix('.sha256').write_text(digest(target) + '\n')


def lock_compose(dest, lock):
    """改写 App CLI 真正读取的 assets，不另建未消费的旁路 catalog。"""
    assets = dest / 'home/arduino/.local/share/arduino-app-cli/assets/0.12.0'
    optional_models = json.loads((HERE / 'optional-models.lock.json').read_text())
    model_catalog = (assets / 'models-list.yaml').read_text()
    for model in optional_models:
        if model['url'] not in model_catalog:
            raise ValueError('App CLI 模型 catalog 不再消费固定 revision：' + model['id'])
    shutil.copy2(HERE / 'optional-models.lock.json', dest / 'usr/share/flange/unoq')
    replacements = {x['tag'].split('/')[-1]: x['image'] for x in lock['images']}
    for path in assets.rglob('*.yaml'):
        lines = path.read_text().splitlines(keepends=True)
        for index, line in enumerate(lines):
            match = re.match(r'^(\s*image:\s*)(.*?)(\r?\n)?$', line)
            if match:
                for suffix, image in replacements.items():
                    if match[2].strip().endswith(suffix):
                        lines[index] = match[1] + image + '\n'
        path.write_text(''.join(lines))


def prepare_containers(dest):
    lock = json.loads((HERE / 'containers.lock.json').read_text())
    cache = dest / 'home/arduino/.cache/flange-containers'
    cache.mkdir(parents=True, exist_ok=True)
    for item in lock['images']:
        prepare_image(item, cache, dest)
    lock_compose(dest, lock)
    (cache / 'containers.lock.json').write_text(json.dumps(lock, indent=2) + '\n')
    (dest / 'usr/share/flange/unoq/containers.lock.json').write_text(json.dumps(lock, indent=2) + '\n')


def main():
    if os.environ.get('FLANGE_TARGET_ARCH') != 'aarch64':
        raise SystemExit('UNO Q 仅支持 aarch64')
    dest = Path(os.environ['DESTDIR'])
    cache = Path(os.environ['FLANGE_APP_WORK_DIR']) / 'downloads'
    resources = json.loads((HERE / 'resources.lock.json').read_text())['resources']
    for resource in resources:
        print('核验并准备 ' + resource['name'], flush=True)
        install_resource(resource, cache, dest)
    finalize(dest)


def privatize_ucm(dest):
    """将板级定制宏隔离，避免覆盖 Ubuntu alsa-ucm-conf 的共享文件。"""
    root = dest / 'usr/share/alsa/ucm2'
    shared = root / 'codecs'
    private = root / 'Qualcomm/qcm2290/codecs'
    if shared.is_dir():
        shutil.copytree(shared, private, dirs_exist_ok=True, symlinks=True)
        shutil.rmtree(shared)
    for path in (root / 'Qualcomm/qcm2290').rglob('*.conf'):
        content = path.read_text().replace('"/codecs/', '"/Qualcomm/qcm2290/codecs/')
        path.write_text(content)


def finalize(dest):
    """把已校验的资源树连接为 Ubuntu 运行时，不执行上游维护脚本。"""
    privatize_ucm(dest)
    # 禁用上游自动改写 MCU、浮动固件修复和固定 gpiod v2 generator。
    for relative in ['etc/initramfs-tools/scripts/local-bottom/ath_bdf_override.sh',
                     'usr/lib/systemd/system-generators/systemd-arduino-router.sh']:
        (dest / relative).unlink(missing_ok=True)
    (dest / 'etc/apt/apt.conf.d/20updateerrors').unlink(missing_ok=True)
    if any(path.is_file() for path in (dest / 'etc/apt').rglob('*')):
        raise ValueError('上游 payload 携带 APT 配置，拒绝混入发行版软件源')
    share = dest / 'usr/share/flange/unoq'
    share.mkdir(parents=True, exist_ok=True)
    shutil.copy2(HERE / 'resources.lock.json', share)
    index = dest / 'home/arduino/.arduino15'
    index.mkdir(parents=True, exist_ok=True)
    shutil.copy2(HERE / 'package_index.json', index)
    shutil.copy2(HERE / 'library_index.json', index)
    identity = {name: digest(HERE / name) for name in
                ['resources.lock.json', 'package_index.json', 'library_index.json', 'models.lock.json', 'optional-models.lock.json']}
    encoded_identity = json.dumps(identity, sort_keys=True, indent=2) + '\n'
    (share / 'environment.lock.json').write_text(encoded_identity)
    (index / 'flange-environment.lock.json').write_text(encoded_identity)
    (index / 'arduino-cli.yaml').write_text(
        'directories:\n  data: /home/arduino/.arduino15\n'
        '  user: /home/arduino/Arduino\n  downloads: /home/arduino/.arduino15/staging\n')
    # 上游固定位置的 OpenOCD 调试入口；明确烧写入口仍由用户调用。
    localbin = dest / 'usr/local/bin'
    localbin.mkdir(parents=True, exist_ok=True)
    for name in ('debug', 'flash', 'reset'):
        (localbin / ('arduino-' + name)).unlink(missing_ok=True)
        (localbin / ('arduino-' + name)).symlink_to('/opt/openocd/bin/arduino-' + name + '.sh')
    (dest / 'home/arduino/.local/share/arduino-cloud-connector').mkdir(parents=True, exist_ok=True)
    state = dest / 'home/arduino/.local/share/arduino-app-cli'
    state.mkdir(parents=True, exist_ok=True)
    # 上游 Compose 使用 /var/lib/arduino-app-cli/models，实际存储归 userdata。
    original = dest / 'var/lib/arduino-app-cli'
    if original.is_dir() and not original.is_symlink():
        shutil.copytree(original, state, dirs_exist_ok=True, symlinks=True)
        shutil.rmtree(original)
    original.parent.mkdir(parents=True, exist_ok=True)
    if not original.exists():
        original.symlink_to('/home/arduino/.local/share/arduino-app-cli')
    prepare_containers(dest)
    # 本地适配最后覆盖上游服务配置，由 AppBuilder 一并封装。
    shutil.copytree(HERE / 'rootfs', dest, dirs_exist_ok=True, symlinks=True)


if __name__ == '__main__':
    main()
