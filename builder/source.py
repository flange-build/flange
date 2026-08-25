"""源码仓库管理 — 替代 Bazel module extensions。"""

import hashlib
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit


class SourceManager:
    """管理组件源码仓库的克隆、更新和本地覆盖。"""

    def __init__(
        self,
        sources_dir: Path = None,
        project_root: Path | None = None,
    ):
        self.sources_dir = sources_dir or Path(".build/sources")
        # project_root 为 None 时，ensure_app 访问本地 components/app/ 时以 cwd
        # 为锚点（保持既有行为与测试兼容）；显式传入可避免依赖当前工作目录。
        self._project_root: Path | None = (
            Path(project_root) if project_root is not None else None
        )
        # 缓存判定前的 ensure 与紧随其后的实际构建共享一次同步结果，避免
        # branch 仓库重复 fetch。每个组件准备时清空，防止跨组件共享仓库跳过
        # 原有的 reset/clean 语义。
        self._prepared_repos: set[tuple[str, str]] = set()
        self._unclean_prepared_repos: set[tuple[str, str]] = set()
        self._builder_reset_prepared_repos: set[tuple[str, str]] = set()
        self._reuse_prepared = False
        self._preparing_cache_inputs = False
        self._builder_resets_source = False

    def prepare_cache_inputs(self, component: str, config: dict) -> None:
        """在缓存判定前同步当前组件会消费的 git 输入。"""
        self._prepared_repos.clear()
        self._unclean_prepared_repos.clear()
        self._builder_reset_prepared_repos.clear()
        self._reuse_prepared = True
        self._preparing_cache_inputs = True
        try:
            source_cfg = config.get(component, {}) or {}
            if source_cfg.get("source"):
                self._builder_resets_source = component in {
                    "kernel", "bootloader"}
                try:
                    self.ensure(component, config)
                finally:
                    self._builder_resets_source = False

            if component == "kernel":
                for name in ("kernel_bsp", "kernel_device"):
                    cfg = config.get(name) or {}
                    if cfg.get("source"):
                        self.ensure_extra(name, cfg, config=config)
                for name, cfg in (source_cfg.get("oot_sources") or {}).items():
                    self.ensure_oot_source(name, cfg, config=config)

            if component == "bootloader":
                self.ensure_firmware(config)
                if "amlogic-boot-fip" in (config.get("sources") or {}):
                    self.ensure_extra(
                        "amlogic-boot-fip",
                        {"source": {"name": "amlogic-boot-fip"}},
                        config=config,
                    )

            if component == "app":
                from builder.config.apps import gather_custom_packages
                for name in gather_custom_packages(config):
                    self.ensure_app(name, config)

            if component == "rootfs":
                for name, cfg in self._repo_firmware(config):
                    self.ensure_extra_firmware(name, cfg, config=config)
        finally:
            self._preparing_cache_inputs = False

    @staticmethod
    def _repo_firmware(config: dict):
        """迭代 rootfs 中的 canonical firmware source。"""
        for entry in (config.get("rootfs") or {}).get("extra_firmware") or []:
            if isinstance(entry.get("source"), dict):
                yield entry.get("name", "firmware"), entry

    def ensure(self, component: str, config: dict) -> Path:
        """按组件的 canonical source 引用确保源码就绪。"""
        return self._ensure_source_ref(
            (config.get(component) or {}).get("source"),
            config,
            component,
        )

    def ensure_extra(self, name: str, cfg: dict,
                     config: dict | None = None) -> Path:
        """按额外组件的 canonical source 引用确保源码就绪。"""
        if config is None:
            raise ValueError(f"ensure_extra({name}) 需要 config 参数")
        return self._ensure_source_ref(cfg.get("source"), config, name)

    @staticmethod
    def source_identity(descriptor: dict) -> str:
        """返回决定远端 checkout 工作树身份的稳定摘要。"""
        payload = json.dumps(
            descriptor, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        return hashlib.sha256(payload).hexdigest()

    def _ensure_source_ref(self, ref, config: dict, label: str) -> Path:
        """解析唯一 source descriptor，获取根目录后追加安全子路径。"""
        if not isinstance(ref, dict) or not ref.get("name"):
            raise ValueError(f"{label}.source.name 未声明")
        name = ref["name"]
        sources = config.get("sources") or {}
        if name not in sources:
            available = ", ".join(sorted(sources)) or "无"
            raise ValueError(
                f"{label}.source.name 引用了未知 source: {name!r}"
                f"（可用: {available}）")

        descriptor = sources[name]
        has_local = bool(descriptor.get("local_path"))
        has_remote = bool(descriptor.get("url"))
        if has_local == has_remote:
            raise ValueError(
                f"sources.{name} 必须且只能声明 local_path 或 url 之一")
        if has_local and any(
            key in descriptor
            for key in ("branch", "commit", "recurse_submodules")
        ):
            raise ValueError(
                f"sources.{name}.local_path 与远端 revision 字段互斥")

        if has_local:
            source_dir = Path(descriptor["local_path"])
            if not source_dir.is_absolute():
                from builder.paths import PROJECT_ROOT
                source_dir = (self._project_root or PROJECT_ROOT) / source_dir
        else:
            source_dir = (
                self.sources_dir / "repos" / self.source_identity(descriptor)
            )
            self._ensure_repo(source_dir, descriptor)

        subpath = ref.get("subpath", "")
        subpath_obj = Path(subpath)
        if subpath_obj.is_absolute() or ".." in subpath_obj.parts:
            raise ValueError(f"{label}.source.subpath 不得越出 source 根目录")
        return source_dir / subpath_obj if subpath else source_dir

    def ensure_firmware(self, config: dict) -> Path:
        """确保平台固件仓库就绪（如 rkbin）。"""
        rkbin_config = config.get("rkbin") or {}
        if not rkbin_config:
            return Path("")
        return self._ensure_source_ref(rkbin_config.get("source"), config, "rkbin")

    def ensure_oot_source(self, name: str, cfg: dict,
                          config: dict | None = None) -> Path:
        """确保 OOT module 的 canonical source 就绪。"""
        if config is None:
            raise ValueError(f"kernel.oot_sources.{name} 需要 config 参数")
        return self._ensure_source_ref(
            cfg.get("source"), config, f"kernel.oot_sources.{name}")

    def ensure_extra_firmware(self, name: str, cfg: dict,
                              config: dict | None = None) -> Path:
        """确保额外固件的 canonical source 或下载 descriptor 就绪。"""
        if cfg.get("url"):
            return self.ensure_download("firmware", name, cfg).parent
        if config is None:
            raise ValueError(f"rootfs.extra_firmware.{name} 需要 config 参数")
        return self._ensure_source_ref(
            cfg.get("source"), config, f"rootfs.extra_firmware.{name}")

    def ensure_extra_deb(self, name: str, cfg: dict) -> Path:
        """确保外部 deb 包已下载。"""
        return self.ensure_download("extra-debs", name, cfg)

    def ensure_prebuilt_image(self, name: str, cfg: dict) -> Path:
        """确保预编镜像已下载。"""
        return self.ensure_download("prebuilt", name, cfg)

    def ensure_download(self, category: str, name: str, cfg: dict) -> Path:
        """按统一 descriptor 下载并校验外部产物。"""
        url = cfg.get("url")
        raw_sha256 = cfg.get("sha256")
        sha256 = raw_sha256.lower() if isinstance(raw_sha256, str) else ""
        if not isinstance(url, str) or not url:
            raise ValueError(f"{name}.url 必须是非空字符串")
        if len(sha256) != 64 or any(
                char not in "0123456789abcdef" for char in sha256):
            raise ValueError(f"{name}.sha256 必须是 64 位十六进制 SHA256")
        filename = cfg.get("filename") or Path(urlsplit(url).path).name
        if (not isinstance(filename, str) or not filename
                or Path(filename).name != filename):
            raise ValueError(f"{name}.filename 必须是安全的单个文件名")
        if Path(category).name != category:
            raise ValueError(f"非法下载类别: {category!r}")

        path = self.sources_dir / "downloads" / category / sha256 / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and self._sha256_file(path) == sha256:
            return path

        partial = path.with_suffix(path.suffix + ".download")
        try:
            subprocess.run(
                ["wget", "-q", "--show-progress", "-O", str(partial), url],
                check=True, timeout=600,
            )
            if self._sha256_file(partial) != sha256:
                raise RuntimeError(
                    f"{name}: sha256 校验失败（URL: {url}）")
            partial.replace(path)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        return path

    @staticmethod
    def _sha256_file(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def ensure_rootfs_tarball(self, config: dict) -> Path:
        """确保 rootfs base tarball 已通过 SHA256 校验并原子落地。"""
        rootfs = config["rootfs"]
        return self.ensure_download("rootfs", "rootfs", rootfs)

    def ensure_app(self, app_name: str, config: dict) -> Path:
        """确保 App 源码就绪，返回 App 目录路径。

        查找顺序（任一层命中即终止，不回退）：
          1. 仓库内 ``<project_root>/components/app/<name>/app.yaml``（本地优先）
          2. ``external_apps[<name>]`` 显式注册：
             - ``local_path`` 分支：直接指向宿主机任意目录，不触发 git
             - ``git`` 分支：克隆到 ``<sources_dir>/apps/<name>/``
          3. ``external_app_dirs`` 搜索路径列表：顺序遍历，首个含
             ``<dir>/<name>/app.yaml`` 的目录命中即采用

        三层未命中时抛出 ValueError，错误信息列出每一层已尝试的路径。

        参数：
            app_name: App 名称
            config:   FINAL_CONFIG 字典，可含 ``external_apps`` /
                      ``external_app_dirs`` 字段

        返回：
            App 目录 Path
        """
        attempted: list[str] = []
        project_root = self._project_root or Path.cwd()

        # ---- 层 1：仓库内 components/app/<name>/ ---------------------------
        local_dir = project_root / "components" / "app" / app_name
        local_yaml = local_dir / "app.yaml"
        if local_yaml.is_file():
            return local_dir
        attempted.append(
            f"本地 {local_dir} "
            f"({'目录不存在' if not local_dir.exists() else 'app.yaml 缺失'})"
        )

        # ---- 层 2：external_apps 显式注册 ----------------------------------
        ext = config.get("external_apps", {}).get(app_name)
        if ext is None:
            attempted.append(f"external_apps[{app_name!r}] 未声明")
        else:
            # 2a. local_path 分支：out-of-tree 本地目录，严格校验后直接返回，
            # 不回退到后续层级（避免隐式降级掩盖用户配置错误）
            if "local_path" in ext:
                local_path = Path(ext["local_path"])
                yaml_path = local_path / "app.yaml"
                if yaml_path.is_file():
                    return local_path
                raise ValueError(
                    f"App '{app_name}': external_apps[{app_name!r}].local_path "
                    f"'{local_path}' "
                    f"{'不存在' if not local_path.exists() else '缺失 app.yaml'}"
                )

            # 2b. git 分支：克隆到 sources_dir/apps/<name>/
            if "git" in ext:
                app_dir = self.sources_dir / "apps" / app_name
                repo_cfg = {**ext, "url": ext["git"]}
                self._ensure_repo(app_dir, repo_cfg)
                return app_dir

            # external_apps 有条目但两个分支都没命中 —— 正常情况下
            # normalize_app_sources 会在解析阶段拦住此分支；这里仅做防御性
            # 报错，不悄悄回退到搜索路径。
            raise ValueError(
                f"App '{app_name}': external_apps[{app_name!r}] 缺少 "
                f"local_path 或 git 字段"
            )

        # ---- 层 3：external_app_dirs 搜索路径 ------------------------------
        for d in config.get("external_app_dirs", []):
            candidate = Path(d) / app_name
            yaml_path = candidate / "app.yaml"
            if yaml_path.is_file():
                return candidate
            attempted.append(
                f"external_app_dirs 下 {candidate} "
                f"({'目录不存在' if not candidate.exists() else 'app.yaml 缺失'})"
            )

        # ---- 三层均未命中 --------------------------------------------------
        bullets = "\n  - ".join(attempted) if attempted else "（无）"
        raise ValueError(
            f"App '{app_name}' 未找到。已尝试：\n  - {bullets}"
        )

    # --- 仓库同步核心 ---

    def _ensure_repo(self, repo_dir: Path, cfg: dict) -> None:
        """统一的 clone + 同步入口。

        四种路径：
          1. repo_dir 不存在 → 首次 clone（按 branch，可选 commit/tag）
          2. 声明了 commit → HEAD 不等时 fetch + checkout，固定到该 commit
          3. 声明了 tag → 解析 tag 对应的 commit；HEAD 不等时 fetch tag +
             checkout，固定到该 tag。tag 与 commit 互斥（声明 tag 时忽略 commit）
          4. 仅声明 branch → fetch + reset --hard origin/<branch>，追远端最新

        约定：声明 branch 不声明 commit/tag 代表"跟随远端"语义，因此 reset --hard
        会丢弃本地修改。要在源码目录里 hack 请改用 local_path。

        recurse_submodules: True 时首次 clone 递归初始化子模块，
        update 时同步更新子模块。
        """
        prepared_key = (
            str(repo_dir.resolve()),
            json.dumps(cfg, sort_keys=True, default=str),
        )
        if self._reuse_prepared and prepared_key in self._prepared_repos:
            if prepared_key in self._unclean_prepared_repos:
                if prepared_key not in self._builder_reset_prepared_repos:
                    subprocess.run(["git", "checkout", "-f", "."],
                                   cwd=repo_dir, check=False)
                    subprocess.run(["git", "clean", "-fd"],
                                   cwd=repo_dir, check=False)
                    if cfg.get("recurse_submodules", False):
                        self._update_submodules(repo_dir)
                self._unclean_prepared_repos.discard(prepared_key)
            return

        clone_url = self._resolve_clone_url(cfg)
        branch = cfg.get("branch", "")
        commit = cfg.get("commit", "")
        tag = cfg.get("tag", "")
        recurse = cfg.get("recurse_submodules", False)

        if not repo_dir.exists():
            # tag 与 commit 在 _clone 内复用 fetch-then-checkout 路径；is_tag
            # 区分两者以决定 fetch 时是否用 ``+refs/tags/<n>:refs/tags/<n>``
            # refspec（非 tag 路径用 commit hash 直接 fetch 即可）。
            ref = commit or tag
            self._clone(
                repo=clone_url,
                branch=branch,
                dest=repo_dir,
                commit=ref,
                recurse=recurse,
                is_tag=bool(tag) and not commit,
            )
            if self._reuse_prepared:
                self._prepared_repos.add(prepared_key)
            return

        if commit:
            if self._rev_parse(repo_dir) != commit:
                self._fetch_checkout(repo_dir, commit)
                if recurse:
                    self._update_submodules(repo_dir)
            if self._reuse_prepared:
                self._prepared_repos.add(prepared_key)
            return

        if tag:
            # tag 是不可变 ref（按约定）。先尝试解析本地 tag→commit，HEAD 已是
            # 目标则跳过；本地无该 tag（或解析失败）则走 fetch + checkout。
            tag_commit = self._rev_parse_ref(repo_dir, f"refs/tags/{tag}^{{}}")
            if tag_commit and self._rev_parse(repo_dir) == tag_commit:
                if self._reuse_prepared:
                    self._prepared_repos.add(prepared_key)
                return
            self._fetch_checkout(repo_dir, tag, is_tag=True)
            if recurse:
                self._update_submodules(repo_dir)
            if self._reuse_prepared:
                self._prepared_repos.add(prepared_key)
            return

        prepared = True
        if branch:
            prepared = self._fetch_reset_branch(repo_dir, branch)
            if recurse and prepared:
                self._update_submodules(repo_dir)
        if self._reuse_prepared:
            self._prepared_repos.add(prepared_key)
            if not prepared:
                self._unclean_prepared_repos.add(prepared_key)
                if self._builder_resets_source and not recurse:
                    self._builder_reset_prepared_repos.add(prepared_key)

    def _update_submodules(self, repo_dir: Path):
        """同步更新子模块到当前 HEAD 声明的版本。"""
        env = {**os.environ,
               "GIT_SSH_COMMAND": "ssh -o StrictHostKeyChecking=accept-new"}
        subprocess.run(["git", "submodule", "update", "--init", "--recursive"],
                       cwd=repo_dir, env=env, check=True, timeout=3600)

    def _resolve_clone_url(self, cfg: dict) -> str:
        """返回 canonical git URL。"""
        return cfg["url"]

    def _clone(self, repo: str, branch: str, dest: Path, commit: str = "",
               recurse: bool = False, is_tag: bool = False):
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
            self._fetch_ref(dest, commit, env=env, is_tag=is_tag)
            subprocess.run(["git", "checkout", commit], cwd=dest, check=True)
            if recurse:
                self._update_submodules(dest)

    def _rev_parse(self, repo_dir: Path) -> str:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir,
                                capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def _rev_parse_ref(self, repo_dir: Path, ref: str) -> str:
        """解析任意 ref（tag / branch / 表达式）到 commit hash；失败返回空字符串。

        用于 tag 幂等性比对：若本地不含该 tag，rev-parse 退出非零，本函数
        返回空字符串，调用方走 fetch + checkout 路径。
        """
        try:
            result = subprocess.run(
                ["git", "rev-parse", ref],
                cwd=repo_dir, capture_output=True, text=True, check=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return ""

    def _fetch_checkout(self, repo_dir: Path, commit: str, is_tag: bool = False):
        env = {**os.environ, "GIT_SSH_COMMAND": "ssh -o StrictHostKeyChecking=accept-new"}
        # 上一次构建应用的 patch 会留下 tracked 修改；先复位当前 HEAD，
        # 否则切到另一块板的 commit 时 checkout 会拒绝覆盖这些文件。
        subprocess.run(["git", "checkout", "-f", "."],
                       cwd=repo_dir, check=False)
        subprocess.run(["git", "clean", "-fd"],
                       cwd=repo_dir, check=False)
        self._fetch_ref(repo_dir, commit, env=env, is_tag=is_tag)
        # 固定 ref 路径继续用 mixed reset + checkout -f，避开 macOS
        # 大小写不敏感文件系统上 kernel 同名异写文件导致的 hard reset 失败。
        subprocess.run(["git", "reset", "--mixed", "--no-refresh", commit],
                       cwd=repo_dir, check=True)
        subprocess.run(["git", "checkout", "-f", "."],
                       cwd=repo_dir, check=False)
        subprocess.run(["git", "clean", "-fd"],
                       cwd=repo_dir, check=False)

    def _fetch_ref(self, repo_dir: Path, ref: str, env: dict, is_tag: bool):
        """fetch 单个 ref。

        commit hash / branch name 直接 ``git fetch origin <ref>`` 即可，git
        会把它写到 FETCH_HEAD，后续 checkout 用同一字符串能命中。

        但 tag name 在浅克隆 + 不带 ``--tags`` 的 fetch 下不会被写到本地
        ``refs/tags/<name>``——只更新 FETCH_HEAD。后续 ``git checkout
        <tagname>`` 找不到 ref 直接失败。修法是用显式 refspec
        ``+refs/tags/<name>:refs/tags/<name>`` 把 tag 拉到本地 ref 空间，
        既能让 checkout 命中，又支持 ``_rev_parse_ref(refs/tags/<tag>)``
        幂等比对（避免每次 build 都重 fetch）。
        """
        if is_tag:
            refspec = f"+refs/tags/{ref}:refs/tags/{ref}"
            subprocess.run(["git", "fetch", "--depth=1", "origin", refspec],
                           cwd=repo_dir, env=env, check=True, timeout=600)
        else:
            subprocess.run(["git", "fetch", "--depth=1", "origin", ref],
                           cwd=repo_dir, env=env, check=True, timeout=600)

    def _fetch_reset_branch(self, repo_dir: Path, branch: str) -> bool:
        """追远端最新，HEAD 变化时优先 hard reset。

        hard reset 只重写新旧 HEAD 间实际变化的文件，能最大程度保留 make
        增量缓存。macOS / Windows 大小写不敏感文件系统上的 Linux kernel
        源码树可能因同名异写文件使 hard reset 失败，此时回退到两步式兼容路径：

          1. git reset --mixed origin/<branch>
             只更新 HEAD + index（二进制 .git/index 文件），不触碰工作
             树，大小写冲突无从发生，必须成功（check=True）。
          2. git checkout -f .
             尽力同步工作树到新 index。遇到大小写冲突会 stderr 报错但
             实际已完成 checkout，exit 非零——与 ComponentBuilder.reset_source
             同策略 check=False 吞掉退出码。

        shallow clone 场景下 `--depth=1` 保持仓库始终是浅的，不会因为
        历次 fetch 逐步长成完整历史。

        先用 ls-remote 比较远端 SHA；未变化时不执行 shallow fetch，避免 Git
        在 kernel 级大仓库上为一次空 fetch 仍遍历全部 shallow objects。

        fetch 必须显式指定 refspec ``+<branch>:refs/remotes/origin/<branch>``：
        ``git clone -b <X>`` 默认建出 single-branch 仓库，``remote.origin.fetch``
        被 pin 到原始分支；后续切到新 branch 时纯 ``git fetch origin <new>``
        只更新 FETCH_HEAD，不建 ``refs/remotes/origin/<new>``，导致下一步
        ``git reset --mixed origin/<new>`` 找不到 ref。显式 refspec 强制建出
        remote tracking ref，single-branch 仓库下首次切 branch 也能成功。

        refspec 前缀 ``+`` 是 force flag——允许 non-fast-forward 更新本地
        ``refs/remotes/origin/<branch>``。上游分支被 rebase / force-push
        （rkbin 这类 vendor binary 仓库常见）时，没有 ``+`` 会被 git 以
        ``! [rejected] ... (non-fast-forward)`` 拒掉。remote tracking ref
        语义上就是镜像远端 tip，跟随 rewind 是预期行为；``git clone`` 默认
        写入 ``remote.origin.fetch`` 的 refspec 同样带 ``+``。
        """
        env = {**os.environ,
               "GIT_SSH_COMMAND": "ssh -o StrictHostKeyChecking=accept-new"}
        refspec = f"+{branch}:refs/remotes/origin/{branch}"
        current_head = self._rev_parse(repo_dir)
        probe = subprocess.run(
            ["git", "ls-remote", "--exit-code", "origin",
             f"refs/heads/{branch}"],
            cwd=repo_dir, env=env, check=False, timeout=600,
            capture_output=True, text=True,
        )
        remote_output = (probe.stdout or "").strip()
        remote_head = (remote_output.split(maxsplit=1)[0]
                       if probe.returncode == 0 and remote_output else "")
        if not remote_head or current_head != remote_head:
            subprocess.run(["git", "fetch", "--depth=1", "origin", refspec],
                           cwd=repo_dir, env=env, check=True, timeout=600)
            remote_head = self._rev_parse_ref(
                repo_dir, f"refs/remotes/origin/{branch}")
        if current_head == remote_head:
            # cache hit 只需要已同步的 commit；不要为检查 dirty 扫描大源码树。
            # miss 后的第二次 ensure 会恢复原有 reset/clean 语义。
            if self._preparing_cache_inputs:
                return False
            # HEAD 未变化时只在确有 tracked 修改（上次构建应用的 patch）时
            # reset 当前 HEAD。`checkout -f .` 会重写内核整树约 9 万个文件的
            # 时间戳，既慢又会破坏 make 增量判断。
            dirty = subprocess.run(
                ["git", "diff-index", "--quiet", "HEAD", "--"],
                cwd=repo_dir, check=False,
            )
            if dirty.returncode:
                result = subprocess.run(
                    ["git", "reset", "--hard", "HEAD"],
                    cwd=repo_dir, check=False,
                )
                if result.returncode:
                    subprocess.run(["git", "checkout", "-f", "."],
                                   cwd=repo_dir, check=False)
            subprocess.run(["git", "clean", "-fd"],
                           cwd=repo_dir, check=False)
            return True
        target = f"origin/{branch}"
        result = subprocess.run(["git", "reset", "--hard", target],
                                cwd=repo_dir, check=False)
        if result.returncode == 0:
            subprocess.run(["git", "clean", "-fd"],
                           cwd=repo_dir, check=False)
            return True

        # `--no-refresh`：跳过 reset 后的 index stat 刷新。kernel 级大树
        # （~90k 文件）在 macOS bind-mount（virtiofs/gRPC-FUSE）下于容器内
        # 刷 index 极慢且会被 SIGKILL（exit 137，git 自身 hint 即建议
        # --no-refresh）。后续 `checkout -f .` 会重新物化工作树，stat 信息
        # 随之更新，跳过刷新无副作用。
        subprocess.run(["git", "reset", "--mixed", "--no-refresh",
                        target],
                       cwd=repo_dir, check=True)
        subprocess.run(["git", "checkout", "-f", "."],
                       cwd=repo_dir, check=False)
        # 切 branch 后清残留：reset --mixed + checkout -f 只把 index 同步到新
        # HEAD，工作树里上一 branch 才有的 tracked 文件会留为 untracked，污染
        # 新 branch 构建（实测：kernel 从 linux-6.18.2 切到 qclinux 6.6 BSP，
        # 残留 8721 个文件；arch/arm64/include/asm/cpucaps.h 是其一，新 BSP
        # Makefile 不再生成 cpucap-defs.h，残留 cpucaps.h 强引用它致编译失败）。
        # `-fd` 不带 `-x`：清未跟踪但保留 gitignored 构建产物（generated/、
        # .o、.cmd），同 branch 增量重建不受影响。
        subprocess.run(["git", "clean", "-fd"],
                       cwd=repo_dir, check=False)
        return True
