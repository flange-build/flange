# qcs6490-extra-apt-sources Specification

## Purpose
TBD - created by archiving change migrate-qcs6490-kernel-702. Update Purpose after archive.
## Requirements
### Requirement: rootfs 构建支持外部 APT 源

`RootfsBuilder` 基类 SHALL 提供 `_setup_extra_apt_sources()` 方法，在 Phase 1 `apt-get update` 之前，将 `config["rootfs"]["extra_apt_sources"]` 中声明的每个外部 APT 源的 GPG key 和 sources.list.d 条目写入目标 rootfs 目录。

每个 source 条目 SHALL 包含以下字段：
- `name`：唯一标识符（用于 key 文件名和 list 文件名）
- `key_url`：ASCII armored GPG public key 的 HTTP URL
- `source`：完整的 sources.list 行（含 `signed-by=` 路径，指向 `/etc/apt/keyrings/<name>.gpg`）

GPG key SHALL 通过 `gpg --dearmor` 转换为二进制格式后写入 `/etc/apt/keyrings/<name>.gpg`；sources 条目 SHALL 写入 `/etc/apt/sources.list.d/<name>.list`。

#### Scenario: 外部 APT 源 key 和 list 正确写入
- **WHEN** config 中声明了 `extra_apt_sources`，且 `_build_phase1` 执行
- **THEN** `apt-get update` 前 rootfs 内 `/etc/apt/keyrings/<name>.gpg` 存在（二进制格式）且 `/etc/apt/sources.list.d/<name>.list` 存在（包含正确 source 行）

#### Scenario: 外部源的包可在 Phase 1 通过 apt 安装
- **WHEN** `extra_apt_sources` 配置了有效 PPA，且 `packages` 列表中包含该 PPA 提供的包名
- **THEN** `apt-get install` 成功安装该包，无 "Unable to locate package" 错误

#### Scenario: 无 extra_apt_sources 时行为不变
- **WHEN** config 中未声明 `extra_apt_sources`（或为空列表）
- **THEN** Phase 1 流程与未引入该能力前完全一致，无副作用

#### Scenario: key 下载失败时构建终止
- **WHEN** `key_url` 无法访问（网络超时或 404）
- **THEN** `curl -fsSL` 非零退出，构建立即报错终止，不生成无效固件的 rootfs 镜像

### Requirement: Docker 构建镜像含 gnupg

flange Docker 构建镜像 SHALL 预装 `gnupg` 包，以支持在构建容器内执行 `gpg --dearmor` 转换 APT key。

#### Scenario: Docker 镜像含 gnupg
- **WHEN** 使用最新 Dockerfile 构建镜像后，在容器内执行 `which gpg`
- **THEN** 命令存在且可执行

