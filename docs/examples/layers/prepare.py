"""在仓库外创建示例工作区，导出固定 Debian arm64 基础镜像并记录摘要。"""
import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--tool-root", type=Path, required=True)
    parser.add_argument("--base-image", default="debian:trixie-slim")
    args = parser.parse_args()
    root = args.directory.resolve()
    if root.exists():
        raise SystemExit("目标目录已存在，请使用新的工作区目录")
    base = Path(__file__).parent
    for name in ("layer-bsp", "layer-common", "layer-debian", "product"):
        shutil.copytree(base / name, root / name, ignore=shutil.ignore_patterns("__pycache__"))
    product = root / "product"
    (product / "flange.toml").write_text(
        'schema_version = 2\ntool_root = ' + json.dumps(str(args.tool_root.resolve())) +
        '\nlayers = ["../layer-bsp", "../layer-common", "../layer-debian", "."]\n')
    metadata = json.loads(subprocess.check_output(["docker", "image", "inspect", args.base_image]))[0]
    if metadata["Architecture"] != "arm64":
        raise SystemExit("基础镜像必须是 Debian 13 arm64；请先 docker pull --platform linux/arm64")
    output = product / ".build"
    output.mkdir()
    archive = output / "debian13-arm64.tar"
    container = subprocess.check_output(["docker", "create", "--platform", "linux/arm64",
                                          metadata["Id"], "/bin/true"], text=True).strip()
    try:
        subprocess.run(["docker", "export", "-o", str(archive), container], check=True)
    finally:
        subprocess.run(["docker", "rm", container], check=True)
    digest = hashlib.file_digest(archive.open("rb"), "sha256").hexdigest()
    descriptor = {"url": archive.as_uri(), "filename": archive.name, "sha256": digest}
    (product / "components/board/layerdemo/base.libsonnet").write_text(
        "// 此工作区实际使用的 Debian 基础归档。\n" + json.dumps(descriptor, indent=2) + "\n")
    (output / "base-source.json").write_text(json.dumps({"image": metadata["Id"], **descriptor}, indent=2))
    print(product)


if __name__ == "__main__":
    main()
