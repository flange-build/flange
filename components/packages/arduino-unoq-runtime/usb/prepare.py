#!/usr/bin/env python3
"""固定 Arduino patched adbd，交由正式 AppBuilder 打包 Ubuntu 自有组件。"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.request

here = Path(__file__).resolve().parent
lock = json.loads((here / 'resources.lock.json').read_text())
cache = Path(os.environ['FLANGE_APP_WORK_DIR']) / 'downloads'
cache.mkdir(parents=True, exist_ok=True)
archive = cache / lock['sha256']
if not archive.is_file():
    with urllib.request.urlopen(lock['url'], timeout=120) as source, archive.open('wb') as target:
        shutil.copyfileobj(source, target)
with archive.open('rb') as source:
    if hashlib.file_digest(source, 'sha256').hexdigest() != lock['sha256']:
        archive.unlink()
        raise ValueError('Arduino adbd 资源摘要不匹配')
dest = Path(os.environ['DESTDIR'])
subprocess.run(['dpkg-deb', '--extract', str(archive), str(dest)], check=True)
# 本地 service 使用修复后的幂等 gadget；不保留含重启缺陷的旧入口。
(dest / 'usr/lib/android-sdk/platform-tools/adbd-usb-gadget').unlink()
(dest / 'usr/lib/systemd/system/adbd.service').unlink()
share = dest / 'usr/share/flange/unoq'
share.mkdir(parents=True, exist_ok=True)
shutil.copy2(here / 'resources.lock.json', share / 'usb-resources.lock.json')
shutil.copytree(here / 'rootfs', dest, dirs_exist_ok=True, symlinks=True)
