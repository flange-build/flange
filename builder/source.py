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

    def ensure_app(self, app_name: str, config: dict) -> Path:
        """确保 App 源码就绪，返回 App 目录路径。

        查找顺序：
          1. 仓库内 app/<app_name>/ 目录（本地开发 App）
          2. board config 中 external_apps 字段声明的外部仓库

        参数：
            app_name: App 名称
            config:   FINAL_CONFIG 字典，可含 external_apps 字段

        返回：
            App 目录 Path

        抛出：
            ValueError: App 既不在本地目录，也未在 external_apps 中声明
        """
        # 步骤 1：优先查找仓库内 app/<name>/ 目录
        local_dir = Path(f"app/{app_name}")
        if local_dir.exists():
            return local_dir

        # 步骤 2：查找 external_apps 配置
        ext = config.get("external_apps", {}).get(app_name)
        if not ext:
            raise ValueError(
                f"App '{app_name}' 未找到：本地目录 {local_dir} 不存在，"
                f"且未在 external_apps 中声明"
            )

        # 步骤 3：克隆外部仓库到 sources/apps/<name>
        app_dir = self.sources_dir / "apps" / app_name
        if not app_dir.exists():
            # tag 优先于 commit，branch 为可选
            commit_ref = ext.get("tag", ext.get("commit", ""))
            branch = ext.get("branch", "")
            self._clone(
                repo=ext["git"],
                branch=branch,
                dest=app_dir,
                commit=commit_ref,
            )
        return app_dir

    def _clone(self, repo: str, branch: str, dest: Path, commit: str = ""):
        dest.parent.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "GIT_SSH_COMMAND": "ssh -o StrictHostKeyChecking=accept-new"}
        # 仅在指定分支时传入 -b 选项；branch 为空时克隆默认分支
        cmd = ["git", "clone", "--depth=1"]
        if branch:
            cmd += ["-b", branch]
        cmd += [repo, str(dest)]
        subprocess.run(cmd, env=env, check=True, timeout=1800)
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
