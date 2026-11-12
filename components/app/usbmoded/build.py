#!/usr/bin/env python3
"""在 flange 的隔离 Docker 工作目录中构建静态 Rust 程序。"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.request


def prepare_toolchain(build_root: Path, arch: str) -> Path:
    manifest_file = Path(__file__).with_name("rust-toolchain-artifacts.json")
    manifest = json.loads(manifest_file.read_text())
    host = {"x86_64": "x86_64", "aarch64": "aarch64"}[platform.machine()]
    host += "-unknown-linux-gnu"
    target = {"armhf": "armv7-unknown-linux-musleabihf",
              "aarch64": "aarch64-unknown-linux-musl"}[arch]
    identity = hashlib.sha256(manifest_file.read_bytes()).hexdigest()[:16]
    root = build_root / "cache" / f"usbmoded-rust-{identity}-{host}-{arch}"
    downloads = build_root / "sources" / "rust"
    downloads.mkdir(parents=True, exist_ok=True)
    root.parent.mkdir(parents=True, exist_ok=True)
    with (downloads / "toolchain.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if (root / ".complete").exists() and (root / "bin/cargo").is_file():
            return root
        if root.exists():
            shutil.rmtree(root)
        for component, triple in [("rustc", host), ("cargo", host), ("rustfmt-preview", host),
                                  ("rust-std", host), ("rust-std", target)]:
            artifact = manifest[f"{component}-{triple}"]
            archive = downloads / artifact["url"].rsplit("/", 1)[1]
            actual = None
            if archive.exists():
                with archive.open("rb") as existing:
                    actual = hashlib.file_digest(existing, "sha256").hexdigest()
            if actual != artifact["sha256"]:
                with tempfile.NamedTemporaryFile(dir=downloads, delete=False) as stream:
                    partial = Path(stream.name)
                    try:
                        print(f"下载 Rust 组件：{archive.name}", flush=True)
                        with urllib.request.urlopen(artifact["url"], timeout=120) as response:
                            shutil.copyfileobj(response, stream)
                        stream.flush()
                        with partial.open("rb") as check:
                            actual = hashlib.file_digest(check, "sha256").hexdigest()
                        if actual != artifact["sha256"]:
                            raise RuntimeError(f"Rust 组件摘要不符：{archive.name}")
                        partial.replace(archive)
                    finally:
                        partial.unlink(missing_ok=True)
            with tempfile.TemporaryDirectory(dir=root.parent) as directory:
                with tarfile.open(archive) as package:
                    package.extractall(directory, filter="data")
                installer = next(Path(directory).glob("*/install.sh"))
                subprocess.run(["sh", str(installer), f"--prefix={root}",
                                "--disable-ldconfig"], check=True)
        (root / ".complete").write_text(identity)
    return root


def main() -> None:
    root = Path(os.environ["FLANGE_BUILD_ROOT"])
    arch = os.environ["FLANGE_TARGET_ARCH"]
    toolchain = prepare_toolchain(root, arch)
    if "--prepare" in sys.argv:
        print(toolchain)
        return
    env = os.environ.copy()
    env["PATH"] = f"{toolchain}/bin:{env['PATH']}"
    env["RUSTC"] = str(toolchain / "bin/rustc")
    env["RUSTDOC"] = str(toolchain / "bin/rustdoc")
    for key in ("RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "CARGO_BUILD_TARGET",
                "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER"):
        env.pop(key, None)
    env["CARGO_HOME"] = str(root / "cache/usbmoded-cargo")
    env["CARGO_TARGET_DIR"] = str(Path(os.environ["FLANGE_APP_WORK_DIR"]) / "cargo")
    target = {"armhf": "armv7-unknown-linux-musleabihf",
              "aarch64": "aarch64-unknown-linux-musl"}[arch]
    # 原生测试在 Docker 内执行；跨编译使用 Rust 自带的 musl CRT 与 rust-lld。
    subprocess.run(["cargo", "fmt", "--check"], env=env, check=True)
    subprocess.run(["cargo", "test", "--locked"], env=env, check=True)
    env["RUSTFLAGS"] = "-C linker=rust-lld -C target-feature=+crt-static"
    subprocess.run(["cargo", "build", "--locked", "--release", "--target", target],
                   env=env, check=True)
    output = Path("out")
    output.mkdir(exist_ok=True)
    for name in ("usbmoded", "usb-mode"):
        shutil.copy2(Path(env["CARGO_TARGET_DIR"]) / target / "release" / name, output / name)
    # 随静态程序保留依赖与标准库的上游许可、版权，不改变第三方归属。
    licenses = Path(os.environ["DESTDIR"]) / "usr/share/doc/usbmoded/licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    packages = tomllib.loads(Path("Cargo.lock").read_text())["package"]
    for package in packages:
        if "source" not in package:
            continue
        name = f"{package['name']}-{package['version']}"
        sources = list((Path(env["CARGO_HOME"]) / "registry/src").glob(f"*/{name}"))
        if len(sources) != 1:
            raise RuntimeError(f"无法定位依赖许可：{name}")
        notices = [p for p in sources[0].iterdir() if p.is_file() and
                   p.name.startswith(("LICENSE", "COPYING", "UNLICENSE", "NOTICE"))]
        if not notices:
            raise RuntimeError(f"依赖未携带许可文件：{name}")
        destination = licenses / name
        destination.mkdir()
        for notice in notices:
            shutil.copy2(notice, destination / notice.name)
    rust_docs = toolchain / "share/doc/rust"
    shutil.copytree(rust_docs / "licenses", licenses / "rust")
    shutil.copy2(rust_docs / "COPYRIGHT-library.html", licenses / "rust")


if __name__ == "__main__":
    main()
