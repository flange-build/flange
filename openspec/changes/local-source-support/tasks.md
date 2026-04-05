## 1. Repository Rule 层改造

- [x] 1.1 修改 `build/kernel_source.bzl`：新增 `local_path` 属性，本地模式下 symlink + watch(.git/index) + 生成 .fetch_stamp 和 .local_mode
- [x] 1.2 修改 `build/bootloader_source.bzl`：同 1.1 的本地模式逻辑

## 2. Extension 层适配

- [x] 2.1 修改 `build/extensions.bzl`：从 board config 读取 `local_path` 并传递给 kernel_source / bootloader_source

## 3. Build Rule 层适配

- [x] 3.1 修改 `build/kernel_build.bzl`：构建脚本检测 `.local_mode` 标记，本地模式下跳过 git reset 和补丁应用
- [x] 3.2 修改 `build/bootloader_build.bzl`：同 3.1 的本地模式逻辑

## 4. Board 配置更新

- [x] 4.1 为所有 board.bzl 的 kernel 和 bootloader 配置添加 `local_path: ""` 默认字段
