#!/usr/bin/env python3
"""检查 Rockchip 多媒体 DEB 集合的分包、metadata 与 WebRTC 文件。"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from builder.app_spec import load_spec


PACKAGE_ROOT = Path(__file__).resolve().parent.parent
WEBRTC_FILES = [
    "usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstwebrtc.so",
    "usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstdtls.so",
    "usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstsrtp.so",
]


def run(command: list[str]) -> str:
    return subprocess.run(
        command,
        check=True,
        text=True,
        capture_output=True,
    ).stdout


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"用法: {sys.argv[0]} <DEB 输出目录>")
    output_dir = Path(sys.argv[1]).resolve()
    # deb 交付分散在 units/ 下产 deb 的那几个单元上，取并集即完整清单。
    expected = [
        name
        for directory in sorted((PACKAGE_ROOT / "units").iterdir())
        if directory.is_dir()
        for name in load_spec(directory).build.deb_outputs
    ]
    debs = [output_dir / name for name in expected]
    missing = [path.name for path in debs if not path.is_file()]
    if missing:
        raise RuntimeError("缺少 DEB: " + ", ".join(missing))

    owners: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="flange-multimedia-") as temp:
        extracted = Path(temp)
        for deb in debs:
            package, version, architecture = deb.name.rsplit("_", 2)
            architecture = architecture.removesuffix(".deb")
            fields = [
                run(["dpkg-deb", "-f", str(deb), field]).strip()
                for field in ("Package", "Version", "Architecture")
            ]
            if fields != [package, version, architecture]:
                raise RuntimeError(f"{deb.name} metadata 与文件名不一致: {fields}")

            for line in run(["dpkg-deb", "-c", str(deb)]).splitlines():
                parts = line.split()
                if len(parts) < 6 or parts[0].startswith("d"):
                    continue
                if parts[1] not in {"root/root", "0/0"}:
                    raise RuntimeError(f"{deb.name} 含非 root 文件: {line}")
                installed_path = parts[5]
                previous = owners.setdefault(installed_path, package)
                if previous != package:
                    raise RuntimeError(
                        f"分包文件冲突: {installed_path} 同属 {previous} 与 {package}"
                    )
            run(["dpkg-deb", "-x", str(deb), str(extracted)])

        missing_webrtc = [
            path for path in WEBRTC_FILES
            if not (extracted / path).is_file()
        ]
        if not list(
            (extracted / "usr/lib/aarch64-linux-gnu").glob(
                "libgstwebrtcnice-1.0.so.0*"
            )
        ):
            missing_webrtc.append(
                "usr/lib/aarch64-linux-gnu/libgstwebrtcnice-1.0.so.0*"
            )
        if missing_webrtc:
            raise RuntimeError("WebRTC runtime 缺失: " + ", ".join(missing_webrtc))

    print(f"检查通过: {len(debs)} 个 DEB，分包无冲突，WebRTC runtime 完整")


if __name__ == "__main__":
    main()
