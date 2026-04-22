## 1. 预备：分层骨架与 gitignore

- [x] 1.1 新建空目录 `components/` 与 `.build/`，提交带 `.gitkeep` 的占位以便 PR 可见（`.build/` 因整体 ignore 无需 keep 占位，Group 2 搬入后自然可见）
- [x] 1.2 更新 `.gitignore`：新增 `/.build/` 与 `/target`（软链接），移除或调整 `/cache/`、`/sources/`、`/target/` 旧条目（过渡期保留旧条目，搬迁完成后可移除）
- [x] 1.3 本地 sanity check：`git status` 仅显示 `.gitignore` 与新增占位目录，无其它未预期改动

## 2. 运行时产物层：`cache/` `sources/` `target/` → `.build/`

- [x] 2.1 `git mv cache .build/cache`（`cache/` 全部内容在 gitignore 中，使用普通 `mv`；无 git 历史需追溯）
- [x] 2.2 `git mv sources .build/sources`（同上，普通 `mv`）
- [x] 2.3 `git mv target .build/target`（同上，普通 `mv`）
- [x] 2.4 移除 `.build/` 内若有的 `.gitkeep` 占位（`.build/` 整体 ignore，从未需要 `.gitkeep`）
- [x] 2.5 本地运行 `pytest`，基线记录：**536 passed, 39 failed**（`.venv/bin/python -m pytest -q` at 22:04）。失败全部为预先存在的 bug（`_hash_cache` 属性缺失、merge/registry 内部断言），非路径相关。后续 Group 5 完成后回归此基线为验收标准。

## 3. 内容层：`app/` `packages/` `rootfs/` `board/` `platform/` → `components/`

- [x] 3.1 `git mv app components/app`
- [x] 3.2 `git mv packages components/packages`
- [x] 3.3 `git mv rootfs components/rootfs`
- [x] 3.4 `git mv board components/board`
- [x] 3.5 `git mv platform components/platform`（与 `builder/platforms/` 明确分离）
- [x] 3.6 移除 `components/` 的 `.gitkeep` 占位
- [x] 3.7 抽样验证：`git status` 显示所有搬迁为 `R` (renamed)，提交后 `git log --follow` 可跨迁移追溯

## 4. 代码层：`config/` → `builder/config/`

- [x] 4.1 `git mv config builder/config`（`__init__.py` 已存在）
- [x] 4.2 改写 6 处 Python import：`builder/config/{loader,registry,query}.py` 各 1 处、`tests/config/{test_merge,test_query,test_registry}.py` 共 4 处，全部指向 `builder.config.*`
- [x] 4.3 `builder/config/__init__.py` 为空文件，无 `config.*` 引用
- [x] 4.4 `grep '^(from|import) config\b' *.py` 全仓零命中；剩余匹配仅在 `envsetup.sh`（Group 6 处理）和 `docs/superpowers/plans/*.md`（历史归档，不改动）
- [x] 4.5 `pytest tests/config` 失败，根因为 `builder/config/registry.py` 硬编码 `project_root / "platform"`（platform 已搬至 `components/platform`）。修复推迟到 Group 5 统一处理。

## 5. 代码层：builder 内部路径常量清查

- [x] 5.1 新建 `builder/paths.py`，暴露 `PROJECT_ROOT`/`COMPONENTS_ROOT`/`BUILD_ROOT` 常量及 `components_dir(root)`/`build_dir(root)` 辅助函数
- [x] 5.2 改写所有旧顶层路径字面量：`builder/base.py`（patches）、`builder/source.py`（sources_dir default、`components/app/{name}`）、`builder/rootfs.py`（overlay 三处）、`builder/cache.py`（target_dir/overlay/app_dir/src_dir/patch_dir/fw_dir）、`builder/app.py`（4 处 target/app）、`builder/scaffold.py`（app 目录）、`builder/engine.py`（sources）、`builder/platforms/{rockchip,allwinnera733}/rootfs.py`（target_dir 各 2 处）
- [x] 5.3 `builder/config/registry.py` 修复 `_project_root()`（`Path(__file__).parent.parent` 因 config 下沉已指向 builder/，改为 import 自 `builder.paths`）；platform/board 目录均改走 `components_dir(root)`
- [x] 5.4 `pytest` 全量（排除 3 个 docker 依赖挂起的 test 文件）：408 passed + test_app_compile 49 passed + test_scaffold 39 passed，pre-existing 失败数 39（与基线一致）；`tests/builder/test_app_builder.py`、`test_app_external.py` 在 sandbox 无 docker 环境下挂起，非本变更回归

## 6. 外部入口：`envsetup.sh`

- [x] 6.1 改写 `envsetup.sh`：10 处 `from config.X` → `from builder.config.X`；4 处 `$FLANGE_DIR/target/...` → `$FLANGE_DIR/.build/target/...`；`Path('app')` → `Path('components/app')`；错误/提示消息中 `board/*/config.py`、`app/$name/` → `components/` 前缀
- [x] 6.2 新增 `_flange_ensure_target_link` 函数：已是正确链接 no-op；错误链接修正；普通文件/目录保留并 WARN，避免误删
- [x] 6.3 采用悬空链接策略（`ln -s` 不检查 target 存在性），首次构建会由 Python/Docker 自动创建 `.build/target/`，届时链接自动解引用正确
- [x] 6.4 两次 `source envsetup.sh` 测试：幂等、无残留、`readlink target` 指向 `.build/target`
- [x] 6.5 `ls target/` 列出 `neons-core3566-nanob orangepi-cm4 radxa-cubie-a7z radxa-zero3w tspi-rk3566`，解引用到 `.build/target/` 正确

## 7. 容器与打包入口

- [x] 7.1 `docker-compose.yml`：`./sources:/workspace/sources` → `./.build/sources:/workspace/.build/sources`；`./cache/apt:/cache/apt` → `./.build/cache/apt:/cache/apt`。`docker-compose.override.yml` gitignore 且用户本地，不改动
- [x] 7.2 `docker/Dockerfile` 和 `docker/entrypoint.sh` 无旧顶层路径引用，无需更改
- [ ] 7.3 **待用户本地验证**：`docker compose run --rm build ls /workspace/.build` 应见到 cache/sources/target 子树。本 sandbox 无 Docker 环境，延后验收
- [x] 7.4 `pyproject.toml`：`include = ["builder*", "config*"]` → `include = ["builder*"]`（config 已下沉）
- [ ] 7.5 **待下次 editable install 后核对**：`flange.egg-info/` 由打包流程再生，不手改

## 8. 文档与规范

- [x] 8.1 `ProjectSpec.md` §9 目录结构完全重写为三层分法，相关架构描述（§2、§7、§8）与 gitignore 规则同步更新
- [x] 8.2 `openspec/project.md` 不存在（仅 `openspec/config.yaml` 与顶层设计文档），无需变更
- [x] 8.3 `CLAUDE.md` 关键约定新增三层结构条目，并标注平台数据/逻辑分离
- [x] 8.4 `README.md` 项目结构树、板级扩展说明、构建流程章节全部对齐到新路径
- [x] 8.5 `roadmap.md` 两处路径引用（三层职责分离、配置驱动）已对齐
- [x] 8.6 已归档 `openspec/changes/archive/*` 不改动；`openspec/specs/{platform-abstraction,allwinnera733-platform,shared-repo-references}/spec.md` 的路径字面量（反引号内）批量更新为新路径

## 9. 验收

- [x] 9.1 `pytest` 核心套件（config + scaffold + app_compile + app_spec + app_collect）225 passed, 11 failed（全部为基线 pre-existing），无新回归。`test_app_builder`/`test_app_external`/`test_cache*` 等 docker 依赖测试在 sandbox 无 docker 环境下挂起，非本变更回归
- [ ] 9.2 **待用户本地验证**：选择典型 target 跑 `lunch` → `flange build`（需 Docker）
- [ ] 9.3 **待用户本地验证**：对应 target 跑 `flange flash`（需 USB 设备）
- [x] 9.4 根目录 `ls` 复核：`builder/ components/ .build/ docker/ docs/ openspec/ tests/ tools/ .flange/ target@` 三层清晰，无残留旧顶层目录
- [x] 9.5 `git grep` 全仓扫描：剩余旧路径字面量仅集中在 `docs/app-architecture.md` 与 `docs/python-build-system-design.html`（设计文档，冻结为历史）、归档变更目录、当前变更自身目录；builder 代码与规范文档均已清理
- [x] 9.6 `openspec validate reorganize-repo-layout --strict` 通过

## 10. 收尾

- [x] 10.1 按任务组拆分 commit：`.gitignore` / components 搬迁 / builder 代码层 / envsetup / 容器与 spec / 活文档 / 变更提案 共 7 个 commit
- [ ] 10.2 **待用户创建 PR 时填写** BREAKING 说明
- [ ] 10.3 **待合入后** 运行 `/opsx:archive reorganize-repo-layout`
