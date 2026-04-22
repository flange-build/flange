"""源码仓库管理 — 替代 Bazel module extensions。"""

import os
import subprocess
from pathlib import Path


class SourceManager:
    """管理组件源码仓库的克隆、更新和本地覆盖。"""

    def __init__(self, sources_dir: Path = None):
        self.sources_dir = sources_dir or Path(".build/sources")

    def ensure(self, component: str, config: dict) -> Path:
        """确保组件源码就绪，返回源码目录路径。

        路径解析优先级：
          1. local_path：直接用本地目录，不碰 git
          2. from_repo + subpath：引用配置中 repos 字典声明的命名仓库
          3. local_repo / repo：独立 clone 到 .build/sources/<component>/<board>/
        """
        comp_config = config.get(component, {})
        local_path = comp_config.get("local_path")
        if local_path:
            return Path(local_path)

        from_repo = comp_config.get("from_repo")
        if from_repo:
            repo_dir = self._ensure_named_repo(from_repo, config)
            subpath = comp_config.get("subpath", "")
            return repo_dir / subpath if subpath else repo_dir

        repo_dir = self.sources_dir / component / config["board"]
        self._ensure_repo(repo_dir, comp_config)
        return repo_dir

    def ensure_extra(self, name: str, cfg: dict,
                     config: dict | None = None) -> Path:
        """确保额外仓库就绪（BSP、device 等），返回仓库目录路径。

        路径解析优先级：
          1. cfg.from_repo + cfg.subpath：引用命名仓库子路径（需传入 config）
          2. cfg.repo / local_repo：独立 clone 到 .build/sources/extra/<name>/
        """
        from_repo = cfg.get("from_repo")
        if from_repo:
            if config is None:
                raise ValueError(
                    f"ensure_extra({name}): from_repo 模式需要传入 config 参数")
            repo_dir = self._ensure_named_repo(from_repo, config)
            subpath = cfg.get("subpath", "")
            return repo_dir / subpath if subpath else repo_dir

        extra_dir = self.sources_dir / "extra" / name
        self._ensure_repo(extra_dir, cfg)
        return extra_dir

    def _ensure_named_repo(self, name: str, config: dict) -> Path:
        """确保命名仓库就绪，返回 .build/sources/repos/<name>/ 路径。

        命名仓库声明在 config["repos"][name] 中，
        多个组件可共享同一命名仓库（只 clone 一次）。
        """
        repos = config.get("repos", {})
        if name not in repos:
            available = ", ".join(sorted(repos)) or "无"
            raise ValueError(
                f"命名仓库未定义：{name}（可用: {available}）"
                f"；请在 config 顶层 repos 字典中声明")
        repo_dir = self.sources_dir / "repos" / name
        self._ensure_repo(repo_dir, repos[name])
        return repo_dir

    def ensure_firmware(self, platform: str, config: dict) -> Path:
        """确保平台固件仓库就绪（如 rkbin）。"""
        rkbin_config = config.get("rkbin", {})
        if not (rkbin_config.get("repo") or rkbin_config.get("local_repo")):
            return Path("")
        fw_dir = self.sources_dir / "firmware" / platform
        self._ensure_repo(fw_dir, rkbin_config)
        return fw_dir

    def ensure_extra_firmware(self, name: str, cfg: dict) -> Path:
        """确保额外固件仓库就绪，返回仓库根目录路径。

        存储路径：.build/sources/extra-firmware/<name>/
        cfg 格式与 rkbin 相同（repo/local_repo/branch/commit）。
        """
        fw_dir = self.sources_dir / "extra-firmware" / name
        self._ensure_repo(fw_dir, cfg)
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
          1. 仓库内 components/app/<app_name>/ 目录（本地开发 App）
          2. board config 中 external_apps 字段声明的外部仓库

        参数：
            app_name: App 名称
            config:   FINAL_CONFIG 字典，可含 external_apps 字段

        返回：
            App 目录 Path

        抛出：
            ValueError: App 既不在本地目录，也未在 external_apps 中声明
        """
        # 步骤 1：优先查找仓库内 components/app/<name>/ 目录
        local_dir = Path(f"components/app/{app_name}")
        if local_dir.exists():
            return local_dir

        # 步骤 2：查找 external_apps 配置
        ext = config.get("external_apps", {}).get(app_name)
        if not ext:
            raise ValueError(
                f"App '{app_name}' 未找到：本地目录 {local_dir} 不存在，"
                f"且未在 external_apps 中声明"
            )

        # 步骤 3：克隆外部仓库到 .build/sources/apps/<name>
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

    # --- 仓库同步核心 ---

    def _ensure_repo(self, repo_dir: Path, cfg: dict) -> None:
        """统一的 clone + 同步入口。

        三种路径：
          1. repo_dir 不存在 → 首次 clone（按 branch，可选 commit）
          2. 声明了 commit → HEAD 不等时 fetch + checkout，固定到该 commit
          3. 仅声明 branch → fetch + reset --hard origin/<branch>，追远端最新

        约定：声明 branch 不声明 commit 代表"跟随远端"语义，因此 reset --hard
        会丢弃本地修改。要在源码目录里 hack 请改用 local_path。

        recurse_submodules: True 时首次 clone 递归初始化子模块，
        update 时同步更新子模块。
        """
        clone_url = self._resolve_clone_url(cfg)
        branch = cfg.get("branch", "")
        commit = cfg.get("commit", "")
        recurse = cfg.get("recurse_submodules", False)

        if not repo_dir.exists():
            self._clone(clone_url, branch, repo_dir, commit, recurse=recurse)
            return

        if commit:
            if self._rev_parse(repo_dir) != commit:
                self._fetch_checkout(repo_dir, commit)
                if recurse:
                    self._update_submodules(repo_dir)
            return

        if branch:
            self._fetch_reset_branch(repo_dir, branch)
            if recurse:
                self._update_submodules(repo_dir)

    def _update_submodules(self, repo_dir: Path):
        """同步更新子模块到当前 HEAD 声明的版本。"""
        env = {**os.environ,
               "GIT_SSH_COMMAND": "ssh -o StrictHostKeyChecking=accept-new"}
        subprocess.run(["git", "submodule", "update", "--init", "--recursive"],
                       cwd=repo_dir, env=env, check=True, timeout=3600)

    def _resolve_clone_url(self, cfg: dict) -> str:
        """选出 clone 源 URL。local_repo 优先于 repo。

        local_repo 转成 file:// 绝对 URL：纯本地路径会被 git 当作 hardlink
        clone 并忽略 --depth=1；file:// 会走 transport，shallow clone 生效。
        """
        local_repo = cfg.get("local_repo", "")
        if local_repo:
            path = Path(local_repo).expanduser().resolve()
            if not path.exists():
                raise ValueError(f"local_repo 不存在: {path}")
            if not (path / ".git").exists() and not (path / "HEAD").exists():
                raise ValueError(
                    f"local_repo 不是一个 git 仓库（未找到 .git 或 HEAD）: {path}"
                )
            return f"file://{path}"
        return cfg["repo"]

    def _clone(self, repo: str, branch: str, dest: Path, commit: str = "",
               recurse: bool = False):
        dest.parent.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "GIT_SSH_COMMAND": "ssh -o StrictHostKeyChecking=accept-new"}
        # recurse_submodules 场景下避免 --depth=1（浅克隆 + 子模块常出问题）
        if recurse:
            cmd = ["git", "clone", "--recurse-submodules"]
        else:
            cmd = ["git", "clone", "--depth=1"]
        if branch:
            cmd += ["-b", branch]
        cmd += [repo, str(dest)]
        subprocess.run(cmd, env=env, check=True, timeout=3600)
        if commit:
            subprocess.run(["git", "fetch", "--depth=1", "origin", commit],
                           cwd=dest, env=env, check=True, timeout=600)
            subprocess.run(["git", "checkout", commit], cwd=dest, check=True)
            if recurse:
                self._update_submodules(dest)

    def _rev_parse(self, repo_dir: Path) -> str:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir,
                                capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def _fetch_checkout(self, repo_dir: Path, commit: str):
        env = {**os.environ, "GIT_SSH_COMMAND": "ssh -o StrictHostKeyChecking=accept-new"}
        subprocess.run(["git", "fetch", "--depth=1", "origin", commit],
                       cwd=repo_dir, env=env, check=True, timeout=600)
        subprocess.run(["git", "checkout", commit], cwd=repo_dir, check=True)

    def _fetch_reset_branch(self, repo_dir: Path, branch: str):
        """追远端最新：fetch origin/<branch> 后两步重置（mixed + checkout）。

        不用 `git reset --hard` 的原因：在 macOS / Windows 大小写不敏感
        文件系统上，Linux kernel 等源码树含仅大小写不同的文件
        （如 xt_connmark.h / xt_CONNMARK.h），`reset --hard` 的 checkout
        阶段会报 "File exists" → 整条命令失败 "fatal: Could not reset
        index file"。两步式拆分：

          1. git reset --mixed origin/<branch>
             只更新 HEAD + index（二进制 .git/index 文件），不触碰工作
             树，大小写冲突无从发生，必须成功（check=True）。
          2. git checkout -f .
             尽力同步工作树到新 index。遇到大小写冲突会 stderr 报错但
             实际已完成 checkout，exit 非零——与 ComponentBuilder.reset_source
             同策略 check=False 吞掉退出码。

        shallow clone 场景下 `--depth=1` 保持仓库始终是浅的，不会因为
        历次 fetch 逐步长成完整历史。
        """
        env = {**os.environ,
               "GIT_SSH_COMMAND": "ssh -o StrictHostKeyChecking=accept-new"}
        subprocess.run(["git", "fetch", "--depth=1", "origin", branch],
                       cwd=repo_dir, env=env, check=True, timeout=600)
        subprocess.run(["git", "reset", "--mixed", f"origin/{branch}"],
                       cwd=repo_dir, check=True)
        subprocess.run(["git", "checkout", "-f", "."],
                       cwd=repo_dir, check=False)
