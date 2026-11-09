"""核验 Docker 经典及 containerd 镜像存储中的固定 config 身份。"""

import hashlib
import json
import re
import subprocess


def verified_image_id(inspect: dict, expected_config: str) -> str | None:
    """返回可被当前 Docker 消费的已验证本地 ID，不使用浮动 tag。"""
    image_id = inspect.get('Id', '')
    if inspect.get('Architecture') != 'arm64' or inspect.get('Os') != 'linux':
        return None
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', image_id):
        return None
    if image_id == expected_config:
        return image_id
    descriptor = inspect.get('Descriptor') or {}
    if descriptor.get('digest') != image_id:
        return None
    # Docker 29 containerd 后端的 ID 指向 manifest；从本地内容库读取并自行核验。
    result = subprocess.run(['ctr', '--namespace', 'moby', 'content', 'get', image_id],
                            capture_output=True, timeout=15)
    if result.returncode or 'sha256:' + hashlib.sha256(result.stdout).hexdigest() != image_id:
        return None
    manifest = json.loads(result.stdout)
    if manifest.get('schemaVersion') != 2 or manifest.get('config', {}).get('digest') != expected_config:
        return None
    return image_id
