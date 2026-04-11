"""源码仓库管理 — 替代 Bazel module extensions。"""

import os
import subprocess
from pathlib import Path


class SourceManager:
    """管理组件源码仓库的克隆、更新和本地覆盖。"""

    def __init__(self, sources_dir: Path = None):
        self.sources_dir = sources_dir or Path("sources")

    def ensure(self, component: str, config: dict) -> Path:
        """确保组件源码就绪，返回源码目录路径。"""
        comp_config = config.get(component, {})
        local_path = comp_config.get("local_path")
        if local_path:
            return Path(local_path)

        repo_dir = self.sources_dir / component / config["board"]
        if not repo_dir.exists():
            self._clone(
                repo=comp_config["repo"],
                branch=comp_config["branch"],
                dest=repo_dir,
                commit=comp_config.get("commit", ""),
            )
        elif comp_config.get("commit"):
            current = self._rev_parse(repo_dir)
            if current != comp_config["commit"]:
                self._fetch_checkout(repo_dir, comp_config["commit"])
        return repo_dir

    def ensure_firmware(self, platform: str, config: dict) -> Path:
        """确保平台固件仓库就绪（如 rkbin）。"""
        rkbin_config = config.get("rkbin", {})
        if not rkbin_config.get("repo"):
            return Path("")
        fw_dir = self.sources_dir / "firmware" / platform
        if not fw_dir.exists():
            self._clone(repo=rkbin_config["repo"], branch=rkbin_config["branch"], dest=fw_dir)
        return fw_dir

    def ensure_rootfs_tarball(self, config: dict) -> Path:
        """确保 rootfs base tarball 已下载。"""
        url = config["rootfs"]["url"]
        tarball_dir = self.sources_dir / "rootfs"
        tarball_dir.mkdir(parents=True, exist_ok=True)
        filename = url.rsplit("/", 1)[-1]
        tarball_path = tarball_dir / filename
        if not tarball_path.exists():
            subprocess.run(["wget", "-q", "-O", str(tarball_path), url],
                           check=True, timeout=600)
        return tarball_path

    def _clone(self, repo: str, branch: str, dest: Path, commit: str = ""):
        dest.parent.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "GIT_SSH_COMMAND": "ssh -o StrictHostKeyChecking=accept-new"}
        subprocess.run(["git", "clone", "--depth=1", "-b", branch, repo, str(dest)],
                       env=env, check=True, timeout=1800)
        if commit:
            subprocess.run(["git", "fetch", "--depth=1", "origin", commit],
                           cwd=dest, env=env, check=True, timeout=600)
            subprocess.run(["git", "checkout", commit], cwd=dest, check=True)

    def _rev_parse(self, repo_dir: Path) -> str:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir,
                                capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def _fetch_checkout(self, repo_dir: Path, commit: str):
        env = {**os.environ, "GIT_SSH_COMMAND": "ssh -o StrictHostKeyChecking=accept-new"}
        subprocess.run(["git", "fetch", "--depth=1", "origin", commit],
                       cwd=repo_dir, env=env, check=True, timeout=600)
        subprocess.run(["git", "checkout", commit], cwd=repo_dir, check=True)
