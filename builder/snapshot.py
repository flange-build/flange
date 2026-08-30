"""Phase 1 base 快照的存取与容量治理。

rootfs 与 recovery 的 Phase 1（解压 ubuntu-base + chroot apt install）耗时以
分钟计，其产物只由「tarball 来源 + 包集合 + arch」决定，与 board/product/
variant 无关。因此快照按内容哈希命名，统一落在 ``.build/target/.cache/``，
跨 board 与 target 维度共享：只要 Phase 1 输入相同就能直接解压复用。

单份快照 0.15–1.2GB，长期迭代会积累（实测曾达 21 份共 12GB，而构建卷只有
120GB）。保存新快照后按最近使用时间回收超出保留份数的旧快照；命中时刷新
mtime，使"保留最近 N 份"是 LRU 而非"最近创建的 N 份"——否则常用的稳定基线
会被一串一次性试验挤掉。

保留份数默认 6，可用环境变量 ``FLANGE_SNAPSHOT_KEEP`` 覆盖；设为 0 关闭回收。
"""

from __future__ import annotations

import os
from pathlib import Path

# 每类快照（rootfs / recovery）默认保留份数。
DEFAULT_KEEP = 6

# 覆盖保留份数的环境变量名。
KEEP_ENV = "FLANGE_SNAPSHOT_KEEP"

# 新快照一律用 zstd：同机实测 gzip -6 约 36MB/s、zstd -3 -T0 约 685MB/s，
# 2.7GiB 的 Phase 1 产物保存从约 76s 降到个位数秒，产物还小 6%。
SNAPSHOT_SUFFIX = ".tar.zst"

# 历史上用 gzip 保存的快照：命中判定仍接受它们（tar 按 magic 自动识别解压），
# 让存量快照继续可用、按 LRU 自然淘汰，不必为换压缩算法付一次全量 Phase 1。
LEGACY_SUFFIXES = (".tar.gz",)

# zstd 压缩参数：-3 是速度/体积的平衡点，-T0 用满可用核心。
ZSTD_COMPRESSOR = "zstd -3 -T0"


def resolve_keep() -> int:
    """解析保留份数；未设置或取值非法时回退默认值。"""
    raw = os.environ.get(KEEP_ENV)
    if raw is None:
        return DEFAULT_KEEP
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_KEEP
    return max(value, 0)


class SnapshotStore:
    """一类 base 快照的存取入口（rootfs 与 recovery 各用一个前缀）。

    参数：
        directory: 快照目录（``.build/target/.cache``）
        prefix:    文件名前缀，如 ``rootfs-base-``
        docker:    DockerRunner，tar 需要特权（快照内含 root 属主与设备节点）
        status:    可选的状态输出回调
    """

    def __init__(self, directory: Path, prefix: str, docker, status=None):
        self.directory = Path(directory)
        self.prefix = prefix
        self.docker = docker
        self._status = status or (lambda _message: None)

    def path_for(self, content_hash: str) -> Path:
        """返回给定内容哈希**保存时**应使用的快照路径。"""
        return self.directory / f"{self.prefix}{content_hash}{SNAPSHOT_SUFFIX}"

    def resolve(self, content_hash: str) -> Path:
        """返回该内容哈希对应的快照路径：已存在的旧格式优先，否则新格式。

        调用方用同一个路径既做命中判定又做保存，因此这里要让存量的 gzip
        快照仍能命中，而未命中时落到 zstd 路径上保存。
        """
        preferred = self.path_for(content_hash)
        if preferred.is_file():
            return preferred
        for suffix in LEGACY_SUFFIXES:
            legacy = self.directory / f"{self.prefix}{content_hash}{suffix}"
            if legacy.is_file():
                return legacy
        return preferred

    def _all_snapshots(self) -> list:
        """列出该类别下的全部快照，含历史压缩格式。"""
        items = []
        for suffix in (SNAPSHOT_SUFFIX, *LEGACY_SUFFIXES):
            items.extend(
                item for item in self.directory.glob(f"{self.prefix}*{suffix}")
                if item.is_file()
            )
        return items

    def restore(self, path: Path, dest: Path) -> None:
        """把快照解压到目标目录，并刷新其 mtime 作为 LRU 依据。"""
        self.docker.run_privileged(["tar", "xf", str(path), "-C", str(dest)])
        try:
            os.utime(path, None)
        except OSError:
            # 只读挂载或属主不符时刷新失败：不影响本次构建，仅退化为按创建
            # 时间回收。
            pass

    def save(self, source_dir: Path, path: Path) -> None:
        """把 Phase 1 产物打包为快照，并回收超额的旧快照。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        self._status(f"保存 base 快照到 {path.name}")
        self.docker.run_privileged(
            ["tar", "-I", ZSTD_COMPRESSOR, "-cf", str(path),
             "-C", str(source_dir), "."])
        removed = self.prune(protect=path)
        if removed:
            self._status(
                f"回收 {len(removed)} 份旧 base 快照: "
                f"{', '.join(item.name for item in removed)}"
            )

    def prune(self, protect: Path | None = None) -> list[Path]:
        """按最近使用时间保留若干份，回收其余；``protect`` 永不回收。"""
        keep = resolve_keep()
        if keep <= 0 or not self.directory.is_dir():
            return []
        candidates = self._all_snapshots()
        candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        protected = {protect.resolve()} if protect else set()
        removed: list[Path] = []
        for item in candidates[keep:]:
            if item.resolve() in protected:
                continue
            try:
                item.unlink()
            except OSError:
                # 并发构建可能已经删掉它；回收是尽力而为，失败不影响构建。
                continue
            removed.append(item)
        return removed
