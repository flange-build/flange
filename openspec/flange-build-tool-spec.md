# flange 构建工具规格

本文档是 flange 构建系统的完整技术规格，按架构层次组织。

---

## 1. 构建环境

### 1.1 Docker 构建容器

#### Requirement: Docker 构建容器基于 Ubuntu 24.04
构建容器 SHALL 基于 `ubuntu:24.04` 镜像，使用 `linux/amd64` 平台架构。

#### Requirement: 容器内预装 aarch64 交叉编译工具链
构建容器 SHALL 预装 `gcc-aarch64-linux-gnu`、`g++-aarch64-linux-gnu`、`qemu-user-static`、`zstd`、`e2fsprogs`、`dosfstools`、`parted`、`fdisk`、`kpartx`。

#### Requirement: 容器内预装 Python 3
构建容器 SHALL 预装 `python3`，并设置 `PYTHONPATH=/workspace` 使构建引擎模块可导入。

#### Requirement: Docker Compose 定义构建服务
项目 SHALL 提供 `docker-compose.yml`，定义名为 `build` 的构建服务，以 `privileged: true` 模式运行。

#### Requirement: 源码仓库通过 volume 持久化
Docker Compose 配置 SHALL 将宿主机 `./sources` 目录映射到容器内 `/workspace/sources`，确保源码仓库跨构建持久化。

#### Requirement: APT 下载缓存通过 volume 持久化
Docker Compose 配置 SHALL 将宿主机 `./cache/apt` 目录映射到容器内 `/cache/apt`。

#### Requirement: SSH 密钥挂载与权限修正
Docker Compose 配置 SHALL 将宿主机 `~/.ssh` 以只读方式挂载到 `/tmp/.ssh-host`。entrypoint SHALL 复制到 `/root/.ssh` 并修正权限。

### 1.2 交叉编译

#### Requirement: 平台策略类直接调用交叉编译器
构建系统 SHALL 通过 `builder/platforms/` 下的策略类直接调用 `aarch64-linux-gnu-gcc` 等工具，无需额外的工具链注册机制。

---

## 2. Python 构建引擎

### 2.1 项目结构

#### Requirement: pyproject.toml 项目配置
项目根目录 SHALL 包含 `pyproject.toml`，声明项目元数据和 pytest 配置。

### 2.2 配置引擎

#### Requirement: 三层配置继承
配置系统 SHALL 支持 platform → SoC → board 三层继承，通过 `config/merge.py` 的 `deep_merge()` 实现。

#### Requirement: 条件标记与追加语义
`deep_merge()` SHALL 支持 `+key` 追加语义（追加到 base 的同名 list）和 `key:condition` 条件标记（匹配 product 或 variant 时生效）。

#### Requirement: 条件解析
`config/merge.py` 的 `resolve_conditions(config, product, variant)` SHALL 将合并后的配置展平为无条件标记的 FINAL_CONFIG dict。匹配的条件标记展开，不匹配的丢弃。

#### Requirement: 统一注册表
`config/registry.py` SHALL 提供 `discover_boards()` 自动扫描 `board/*/config.py`，`get_board_config()` 三层合并，`resolve_config()` 完整配置解析。

#### Requirement: 板级配置自动发现
注册表 SHALL 通过 `importlib.util.spec_from_file_location` 加载板级配置，支持包含连字符的目录名。

#### Requirement: target 查询与解析
`config/query.py` SHALL 提供 `get_valid_targets()` 枚举合法 target 组合，`parse_target()` 解析 `<board>-<product>-<variant>` 格式。

### 2.3 构建引擎

#### Requirement: 依赖图管理
`builder/engine.py` SHALL 定义组件依赖图（kernel→boot→image, bootloader→image, rootfs→image），按拓扑序调度构建。

#### Requirement: 内容哈希增量构建
`builder/cache.py` SHALL 基于组件配置值、源码 commit、补丁文件内容的 SHA256 哈希判断组件是否需要重建。

#### Requirement: Docker 容器执行
`builder/docker.py` SHALL 封装 `docker compose run` 调用，支持普通模式和 privileged 模式。

#### Requirement: 源码仓库管理
`builder/source.py` SHALL 管理源码仓库的 shallow clone、commit 锁定、本地路径覆盖和固件仓库（rkbin）。

---

## 3. 组件架构

### 3.1 框架与策略分离

#### Requirement: ComponentBuilder 基类
`builder/base.py` SHALL 定义 `ComponentBuilder` ABC，提供 `build()` 流程（ensure source → reset → patches → configure → compile → collect）和 `make()` 工具方法。

#### Requirement: 平台策略子类
每个平台 SHALL 在 `builder/platforms/<vendor>/` 下提供策略子类，实现 `configure()`、`compile()`、`collect()` 抽象方法。

#### Requirement: ChrootContext 安全管理
`builder/chroot.py` SHALL 提供 `ChrootContext` 上下文管理器，自动管理 proc/sys/dev 挂载和 umount，确保异常时也能清理。

### 3.2 补丁归属

#### Requirement: 平台级补丁
平台通用补丁 SHALL 存放在 `platform/<vendor>/patches/<component>/` 目录。

#### Requirement: 板级补丁
板级特有补丁 SHALL 存放在 `board/<name>/patches/<component>/` 目录。

#### Requirement: 补丁应用顺序
ComponentBuilder SHALL 先应用平台补丁，再应用板级补丁，均按文件名排序。

---

## 4. 分区表系统

#### Requirement: 分区表中间格式
`builder/partition/__init__.py` SHALL 定义 `PartitionTable` 和 `Partition` dataclass 作为中间格式。

#### Requirement: Rockchip 分区转换
`builder/partition/rockchip.py` SHALL 将中间格式转换为 Rockchip parameter.txt（CMDLINE mtdparts 格式）。idbloader 不纳入 mtdparts。

#### Requirement: 分区配置来源
分区表 SHALL 从 FINAL_CONFIG 的 `partitions` 字段读取，支持 SoC 默认值和 product 级覆盖。

---

## 5. Flash 系统

#### Requirement: flash.sh 自动生成
`builder/flash/generate.py` 的 `FlashConfigGenerator` SHALL 从 FINAL_CONFIG 生成 `flash-config.json`，描述每个分区的镜像、偏移与保护属性；宿主机侧由 `builder/flash/execute.py` 读取它执行刷写。

#### Requirement: 刷写工具配置化
flash.sh 中的刷写工具 SHALL 从 FINAL_CONFIG 的 `flash_tool` 字段读取。

#### Requirement: 刷写在宿主机执行
刷写操作 SHALL 在宿主机执行（非 Docker 容器内），通过 USB 连接目标设备。

---

## 6. CLI 用户接口

#### Requirement: envsetup.sh 初始化
`source envsetup.sh` SHALL 注册 `lunch` 和 `flange` 函数到当前 shell，兼容 bash 和 zsh。

#### Requirement: lunch 配置选择
`lunch` SHALL 支持完整指定（`<board>-<product>-<variant>`）、仅指定 board（使用默认 product/variant）、部分覆盖（`--variant=debug`）和交互式菜单。

#### Requirement: .flange/current_config 持久化
lunch 选择的配置 SHALL 持久化为 JSON 到 `.flange/current_config`，下次 `source envsetup.sh` 时自动恢复。

#### Requirement: flange 子命令
flange SHALL 提供 `build`、`flash`、`clean`、`status`、`shell`、`docker` 子命令。
