"""源码仓库管理 — 替代 Bazel module extensions。"""

import hashlib
import json
import os
import subprocess
from pathlib import Path


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
            if any(source_cfg.get(key) for key in
                   ("local_path", "from_repo", "repo", "local_repo")):
                self._builder_resets_source = component in {
                    "kernel", "bootloader"}
                try:
                    self.ensure(component, config)
                finally:
                    self._builder_resets_source = False

            if component == "kernel":
                for name in ("kernel_bsp", "kernel_device"):
                    cfg = config.get(name) or {}
                    if any(cfg.get(key) for key in
                           ("from_repo", "repo", "local_repo")):
                        self.ensure_extra(name, cfg, config=config)
                for name, cfg in (source_cfg.get("oot_sources") or {}).items():
                    if (name not in ("product", "variant")
                            and isinstance(cfg, dict)):
                        self.ensure_oot_source(name, cfg)

            if component == "bootloader":
                self.ensure_firmware(config.get("platform", ""), config)
                if "amlogic-boot-fip" in (config.get("repos") or {}):
                    self.ensure_extra(
                        "amlogic-boot-fip",
                        {"from_repo": "amlogic-boot-fip"},
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
        """迭代 rootfs 中具有独立 git 仓库的 firmware 声明。"""
        for entry in (config.get("rootfs") or {}).get("extra_firmware") or []:
            if entry.get("source", "repo") == "repo":
                yield entry.get("name", "firmware"), entry

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

    # extra_firmware source 类型注册表 —— 复用其他组件已 ensure 的源码树
    # 而非独立 clone。调用方（_install_extra_firmware）需在 component_sources
    # dict 中提供对应路径。新增 source 类型只需在此添加，无需扩展 API。
    _COMPONENT_FIRMWARE_SOURCES = frozenset({"kernel", "bootloader"})

    def ensure_oot_source(self, name: str, cfg: dict) -> Path:
        """确保 out-of-tree 模块源码就绪，返回源码根目录路径。

        存储路径：``.build/sources/oot-modules/<name>/``。cfg 字段与 rkbin
        相同（``repo`` / ``local_repo`` / ``branch`` / ``commit`` / ``tag`` /
        ``recurse_submodules``），_ensure_repo 复用同一套语义：

        - 仅声明 branch（无 commit/tag）：每次 ensure 跟踪远端最新（reset --hard）
        - 声明 commit/tag：固定锁定

        与 extra_firmware 的 source="repo" 形态平行，但语义不同：本函数返回
        的路径是**编译输入**（make M=<path>），而 extra_firmware 是**rootfs
        内容来源**。强行复用 extra_firmware 会把 .build/sources/extra-firmware/
        目录当编译目录，造成增量构建残留 .o/.ko 污染固件部署。
        """
        repo_dir = self.sources_dir / "oot-modules" / name
        self._ensure_repo(repo_dir, cfg)
        return repo_dir

    def ensure_extra_firmware(self, name: str, cfg: dict,
                              component_sources: dict[str, Path]
                              | None = None,
                              config: dict | None = None) -> Path:
        """确保额外固件来源就绪，返回固件根目录路径。

        cfg 的 ``source`` 字段决定来源类型（默认 ``"repo"``）：

        - ``"repo"``：从外部 git 仓库 clone（沿用历史行为）。其他字段按
          rkbin 格式：``repo`` / ``local_repo`` / ``branch`` / ``commit``。
          存储路径 ``.build/sources/extra-firmware/<name>/``。
        - ``"kernel"`` / ``"bootloader"``：复用对应 component 已 ensure 的
          源码树作为 fw_dir，**不**独立 clone。调用方需在 ``component_sources``
          中提供 ``{"kernel": <kernel_src_path>, ...}``。适用于 firmware
          blob 在 BSP 源码内 vendor 的场景（如 RK3588 的
          ``drivers/gpu/arm/bifrost/mali_csffw.bin``）。
        - ``"oot:<name>"``：复用同 build 内已 ensure 的 OOT 模块源码作为
          fw_dir。调用方需在 ``component_sources`` 中以同 key
          （``"oot:<name>"``）提供路径。适用于 vendor WiFi/BT 包内自带固件
          blob 的场景（如 rkwifibt 的 ``firmware/realtek/RTL8852BE/``）。
        - ``"local"``：板目录下随仓库携带的本地 blob，**不**走 git/网络。
          cfg 需带 ``src_dir`` 字段，相对 ``components/board/<board>/`` 解析为
          fw_dir。调用方需通过 ``config`` 参数提供顶层 config（取 ``board``
          字段）。适用于触摸 cfg blob / 板私有 panel firmware 等小尺寸、
          按 product 条件部署、不便走仓库的场景。

        将来扩展：``"url"`` / 其他 component 类型只需在此函数与
        ``_COMPONENT_FIRMWARE_SOURCES`` 中添加分支，调用方按需在
        ``component_sources`` 注入对应 path。
        """
        source_type = cfg.get("source", "repo")
        if source_type == "repo":
            fw_dir = self.sources_dir / "extra-firmware" / name
            self._ensure_repo(fw_dir, cfg)
            return fw_dir
        if (source_type in self._COMPONENT_FIRMWARE_SOURCES
                or source_type.startswith("oot:")):
            if not component_sources or source_type not in component_sources:
                raise ValueError(
                    f"extra_firmware {name} 声明 source={source_type!r}，"
                    f"但调用方未在 component_sources 中提供对应路径")
            return component_sources[source_type]
        if source_type == "local":
            return self._ensure_local_firmware(name, cfg, config)
        raise ValueError(
            f"extra_firmware {name} 不支持的 source 类型: {source_type!r}；"
            f"可选: 'repo' / 'local' / 'oot:<name>' / "
            f"{' / '.join(sorted(repr(s) for s in self._COMPONENT_FIRMWARE_SOURCES))}")

    def _ensure_local_firmware(self, name: str, cfg: dict,
                               config: dict | None) -> Path:
        """source='local' 分支：解析 components/board/<board>/<src_dir>。

        与 source='repo' 平行的"零网络"通路；fw_dir 直接指向仓库内目录，
        cache 层另行 hash 文件内容以保证 blob 变更触发 rootfs 重建。
        """
        if config is None or not config.get("board"):
            raise ValueError(
                f"extra_firmware {name} 声明 source='local'，"
                f"但 ensure_extra_firmware 未收到含 'board' 字段的 config")
        src_dir = cfg.get("src_dir")
        if not src_dir:
            raise ValueError(
                f"extra_firmware {name} 声明 source='local' 但缺 'src_dir' 字段")
        # PROJECT_ROOT 是 paths.py 暴露的仓库根；优先使用 self._project_root
        # 让测试可注入临时根。
        from builder.paths import COMPONENTS_DIRNAME, PROJECT_ROOT
        root = self._project_root if self._project_root is not None else PROJECT_ROOT
        fw_dir = (root / COMPONENTS_DIRNAME / "board"
                  / config["board"] / src_dir).resolve()
        if not fw_dir.is_dir():
            raise FileNotFoundError(
                f"extra_firmware {name} source='local' 引用的目录不存在: {fw_dir}")
        return fw_dir

    def ensure_extra_deb(self, name: str, cfg: dict) -> Path:
        """确保外部 deb 包已下载，返回 deb 文件路径。

        存储路径：.build/sources/extra-debs/<name>/<filename>
        cfg 格式：
          - url:     下载地址（必须）
          - sha256:  校验哈希（必须）
          - filename: 本地文件名（可选，默认从 URL 提取）
        下载使用原子写入（.download 后缀），sha256 不匹配则删除重下。
        """
        url = cfg["url"]
        sha256 = cfg["sha256"]
        filename = cfg.get("filename", url.rsplit("/", 1)[-1])
        deb_dir = self.sources_dir / "extra-debs" / name
        deb_dir.mkdir(parents=True, exist_ok=True)
        deb_path = deb_dir / filename

        # 已存在且校验通过则跳过
        if deb_path.is_file() and self._sha256_file(deb_path) == sha256:
            return deb_path

        # 原子下载：先写 .download，完成后 rename；
        # 失败时清理残留 partial 文件，避免污染缓存目录。
        partial = deb_path.with_suffix(deb_path.suffix + ".download")
        try:
            subprocess.run(
                ["wget", "-q", "--show-progress", "-O", str(partial), url],
                check=True, timeout=600,
            )
            if self._sha256_file(partial) != sha256:
                raise RuntimeError(
                    f"extra_deb {name}: sha256 校验失败（URL: {url}）")
            partial.rename(deb_path)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        return deb_path

    def ensure_prebuilt_image(self, name: str, cfg: dict) -> Path:
        """确保预编固件镜像（如 SPI bootloader spi.img）已下载，返回文件路径。

        存储路径：.build/sources/prebuilt/<name>/<filename>
        cfg 格式（与 ensure_extra_deb 同款）：
          - url:      下载地址（必须）
          - sha256:   校验哈希（必须）
          - filename: 本地文件名（可选，默认从 URL 提取）
        原子写入（.download 后缀）+ sha256 校验；缓存命中（文件在且哈希匹配）则
        跳过下载——故同一构建/刷写多次调用幂等、无网亦可复用已下产物。
        """
        url = cfg["url"]
        sha256 = cfg["sha256"]
        filename = cfg.get("filename", url.rsplit("/", 1)[-1])
        img_dir = self.sources_dir / "prebuilt" / name
        img_dir.mkdir(parents=True, exist_ok=True)
        img_path = img_dir / filename

        if img_path.is_file() and self._sha256_file(img_path) == sha256:
            return img_path

        partial = img_path.with_suffix(img_path.suffix + ".download")
        try:
            subprocess.run(
                ["wget", "-q", "--show-progress", "-O", str(partial), url],
                check=True, timeout=600,
            )
            if self._sha256_file(partial) != sha256:
                raise RuntimeError(
                    f"prebuilt_image {name}: sha256 校验失败（URL: {url}）")
            partial.rename(img_path)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        return img_path

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
        url = rootfs["url"]
        raw_sha256 = rootfs.get("sha256")
        sha256 = raw_sha256.lower() if isinstance(raw_sha256, str) else ""
        if len(sha256) != 64 or any(
                char not in "0123456789abcdef" for char in sha256):
            raise ValueError("rootfs.sha256 必须是 64 位十六进制 SHA256")
        tarball_dir = self.sources_dir / "rootfs"
        tarball_dir.mkdir(parents=True, exist_ok=True)
        filename = url.rsplit("/", 1)[-1]
        tarball_path = tarball_dir / filename
        if (tarball_path.is_file()
                and self._sha256_file(tarball_path) == sha256):
            return tarball_path

        partial = tarball_path.with_suffix(tarball_path.suffix + ".download")
        try:
            subprocess.run(
                ["wget", "-q", "--show-progress", "-O", str(partial), url],
                check=True, timeout=600,
            )
            if self._sha256_file(partial) != sha256:
                raise RuntimeError(
                    f"rootfs tarball sha256 校验失败（URL: {url}）")
            partial.replace(tarball_path)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        return tarball_path

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
                repo_cfg = {**ext, "repo": ext["git"]}
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
