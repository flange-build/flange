## 1. app.yaml Schema 定义与解析

- [ ] 1.1 定义 app.yaml 完整 JSON Schema（或 Python dataclass），覆盖所有字段：app（name/version/description/type/arch）、maintainer、capabilities、build（system/options/outputs/deps/commands）、install、systemd（unit/auto_start）、depends、conffiles、data_dirs、lib（headers_dir/dev_suffix）
- [ ] 1.2 实现 `builder/app_spec.py`：`AppSpec` dataclass + `load_spec(app_dir: Path) -> AppSpec` 函数，用 `yaml.safe_load` 解析 app.yaml，做字段类型校验和默认值填充
- [ ] 1.3 编写 `tests/builder/test_app_spec.py`：测试 4 种 type 的 app.yaml 解析、缺失必填字段报错、默认值填充、build.system 各取值验证
- [ ] 1.4 扩展 `app/adbd/app.yaml`：增加 install 映射（`bin/adbd-arm64: /usr/bin/adbd`、`conf/usbdevice.conf: /etc/usbdevice.conf` 等）和 systemd 段（`unit: systemd/usbdevice.service`、`auto_start: true`）

## 2. deb 打包核心引擎

- [ ] 2.1 实现 `builder/deb.py`：`DebBuilder` 类，职责为文件树 + control 元数据 → .deb 文件
  - `build_deb(name, version, arch, control_fields, files, output_dir) -> Path`
  - `files`: `list[tuple[src_path, install_path, mode]]`
  - 使用 `tarfile` 构建 control.tar.gz 和 data.tar.gz
  - 使用 `ar` 命令组合 debian-binary + control.tar.gz + data.tar.gz → .deb
- [ ] 2.2 实现 control 文件生成：从 AppSpec 生成 `control`（Package/Version/Architecture/Maintainer/Description/Depends）、`conffiles`、`postinst`（systemd enable + 数据目录创建，兼容 chroot）、`prerm`（systemd disable）
- [ ] 2.3 编写 `tests/builder/test_deb.py`：
  - 测试 control 文件生成内容正确性
  - 测试 conffiles 生成（无空行问题）
  - 测试 postinst 脚本的 chroot 兼容逻辑
  - 测试 data.tar.gz 文件树结构和权限
  - 端到端测试：构建 .deb → `ar t` 验证结构 → 解压验证内容

## 3. 约定式路径映射与架构选择

- [ ] 3.1 实现 `builder/app.py` 中的 `_collect_files(app_dir, spec, arch) -> list[tuple]`：
  - 约定映射：遍历 app 目录的 bin/lib/conf/scripts/systemd/udev/res/include 子目录，按默认规则映射
  - 显式覆盖：如果 app.yaml 有 `install` 段，按声明映射
  - 预编译架构选择：匹配 `-arm64`/`-aarch64`/`-armhf`/`-arm32` 后缀，去后缀后重命名
- [ ] 3.2 编写测试：约定映射生成的文件列表、显式 install 覆盖、架构后缀匹配与重命名、不匹配架构的文件被排除

## 4. AppBuilder 核心逻辑

- [ ] 4.1 实现 `builder/app.py`：`AppBuilder` 类
  - `__init__(self, docker, source, config)` — 接收 DockerRunner、SourceManager、FINAL_CONFIG
  - `build_all() -> dict[str, Path]` — 构建所有 custom_packages，返回 {app_name: deb_path}
  - `build_one(app_name) -> Path` — 构建单个 App 的 .deb
  - 内部流程：`_load_spec` → `_resolve_build_order` → 逐个 `_compile` → `_collect_files` → `DebBuilder.build_deb`
- [ ] 4.2 实现 App 间依赖拓扑排序 `_resolve_build_order(app_names) -> list`：解析各 App 的 `build.deps`，调用 `_topo_sort`，检测循环依赖并报错
- [ ] 4.3 编写测试：单个 App 构建流程、多个 App 拓扑排序、循环依赖检测

## 5. 构建系统调用

- [ ] 5.1 实现 `builder/app.py` 中的 `_compile(app_dir, spec, config)`：
  - 根据 `build.system` 查找命令模板（none/cmake/meson/make/swift/custom）
  - 展开 `build.options` 为命令行参数
  - 交叉编译参数注入（ARCH、CROSS_COMPILE、sysroot）
  - 通过 `DockerRunner` 在容器内执行
- [ ] 5.2 实现 `build.system: custom` 逃生通道：直接执行 `build.commands` 列表
- [ ] 5.3 编写测试：各构建系统的命令生成（验证命令模板展开结果），custom 命令直通

## 6. lib 双包产出

- [ ] 6.1 实现 lib 类型的双包打包逻辑：
  - 运行时包（`lib<name>`）：收集 `lib/` 下的 .so 文件
  - 开发包（`lib<name>-dev`）：收集 `include/` 下头文件 + `lib/` 下 .a 文件，Depends 包含运行时包
- [ ] 6.2 实现 sysroot 安装：lib 构建后将头文件和 .so 复制到 `target/<board>/<product>/<variant>/sysroot/usr/`
- [ ] 6.3 编写测试：lib 双包产出验证（两个 .deb 的 control 和 data 内容）、sysroot 目录结构

## 7. 仓库外 App 支持

- [ ] 7.1 扩展 `builder/source.py`：新增 `ensure_app(app_name, config) -> Path` 方法，先查 `app/<name>`，再查 `external_apps` 配置，克隆到 `sources/apps/<name>`
- [ ] 7.2 扩展 config schema：在 board config 中支持 `external_apps` 字段声明
- [ ] 7.3 编写测试：仓库内 App 查找、仓库外 App 克隆路径、未找到 App 报错

## 8. 构建引擎集成

- [ ] 8.1 修改 `builder/engine.py`：依赖图新增 `"app": []` 节点，rootfs 依赖改为 `"rootfs": ["app"]`
- [ ] 8.2 修改 `BuildEngine._get_builder`：当 component 为 "app" 时返回 AppBuilder 实例（不走平台策略工厂）
- [ ] 8.3 扩展 `builder/cache.py`：App 组件的 content hash 包含 app.yaml 内容 + App 源文件哈希
- [ ] 8.4 编写测试：依赖图拓扑排序包含 app、构建顺序正确（app 在 rootfs 之前）

## 9. Rootfs 集成

- [ ] 9.1 修改 `builder/platforms/rockchip/rootfs.py` Phase 2：在 overlay 复制之后、压缩之前，遍历 `custom_packages` 并 `dpkg -i` 安装对应 .deb
- [ ] 9.2 .deb 文件传递：AppBuilder 将产物输出到 `target/<board>/<product>/<variant>/app/`，rootfs builder 从该目录读取
- [ ] 9.3 编写测试：rootfs Phase 2 流程包含 dpkg -i 调用

## 10. CLI 命令

- [ ] 10.1 修改 `envsetup.sh`：新增 `flange build app [name]` 子命令，调用 `AppBuilder.build_all()` 或 `AppBuilder.build_one(name)`
- [ ] 10.2 新增 `flange list apps` 子命令：扫描 `app/` 目录 + `external_apps` 配置，列出所有可用 App 及其类型
- [ ] 10.3 新增 `flange create app <name> --type=<type> --build-system=<system>` 子命令：调用脚手架生成器

## 11. 脚手架生成器

- [ ] 11.1 实现 `builder/scaffold.py`：`AppScaffold` 类
  - `create(name, app_type, build_system, target_dir)` — 生成 App 工程目录
  - 使用 `string.Template` 渲染模板文件
- [ ] 11.2 创建模板文件 `builder/templates/`：
  - `app.yaml.tpl` — 通用 app.yaml 模板
  - `exec/cmake/`、`exec/meson/`、`exec/make/`、`exec/swift/`、`exec/none/` — exec 类型各构建系统模板
  - `service/cmake/`、`service/systemd/`、`service/conf/` — service 类型模板
  - `lib/cmake/`、`lib/meson/`、`lib/make/` — lib 类型模板（含 include + src）
  - `test/none/scripts/` — test 类型模板
- [ ] 11.3 编写测试：各 type × build-system 组合生成的目录结构和文件内容验证

## 12. 文档同步

- [ ] 12.1 更新 `docs/app-architecture.md`：移除所有 Bazel/Starlark/BUILD.bazel 引用，用 Python 实现描述替代，更新数据流图、目录结构、CLI 示例，移除迁移状态提示
- [ ] 12.2 更新 `README.md`：在 flange 命令表中新增 `build app`、`create app`、`list apps`

## 13. 端到端验证

- [ ] 13.1 用 adbd 做端到端测试：`app/adbd/app.yaml` → `AppBuilder.build_one("adbd")` → 产出 `adbd_1.0.0_arm64.deb` → 验证 deb 内容（control 字段、文件树、postinst 脚本）
- [ ] 13.2 验证 rootfs 集成链路：engine.build("rootfs") 时自动先构建 adbd .deb，Phase 2 安装到 rootfs
