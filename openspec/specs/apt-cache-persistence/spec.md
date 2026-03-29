### Requirement: APT 下载缓存 Docker volume 挂载
`docker-compose.yml` SHALL 将宿主机 `./cache/apt` 目录挂载到容器内 `/cache/apt`，用于持久化 APT .deb 下载文件。

#### Scenario: APT 缓存 volume 挂载
- **WHEN** 查看 `docker-compose.yml` 的 volumes 配置
- **THEN** 包含 `./cache/apt:/cache/apt` 挂载

#### Scenario: 容器重建后 APT 缓存保留
- **WHEN** 销毁并重建构建容器后执行 rootfs 构建
- **THEN** 之前下载的 .deb 文件仍在 `/cache/apt` 中可用

### Requirement: rootfs_base 策略脚本使用 APT 缓存
rootfs base 平台构建脚本 SHALL 将 `ROOTFS_APT_CACHE_DIR` 目录 bind-mount 到 chroot 的 `/var/cache/apt/archives/`，使 apt-get install 命中已缓存的 .deb 文件。构建完成后 SHALL 正确 unmount。

#### Scenario: APT 缓存 bind-mount
- **WHEN** build_base.sh 在 chroot 内执行 apt-get install
- **THEN** `/var/cache/apt/archives/` 指向宿主机持久化缓存目录

#### Scenario: 新下载的 .deb 自动缓存
- **WHEN** apt-get install 下载了新的 .deb 文件
- **THEN** 新文件自动写入宿主机缓存目录，下次构建可复用

#### Scenario: APT 缓存目录不存在时
- **WHEN** `ROOTFS_APT_CACHE_DIR` 为空或目录不存在
- **THEN** 跳过 bind-mount，apt-get install 正常执行（不使用缓存）
