## 1. flange_deb 规则实现

- [x] 1.1 创建 `build/deb.bzl`：实现 `flange_deb` rule 的属性定义和 `_flange_deb_impl` 函数框架
- [x] 1.2 实现 data.tar.gz 构建逻辑：按 `paths` 映射组织文件树，设置正确权限（二进制/脚本 755，配置/资源 644）
- [x] 1.3 实现 control 文件生成：从 version/description/maintainer/architecture/runtime_deps 属性生成
- [x] 1.4 实现 conffiles 生成：从 `conffiles` 属性逐行写入，确保无末尾空行
- [x] 1.5 实现 systemd 集成：unit 文件安装到 `/lib/systemd/system/`，生成 postinst（systemctl enable）和 prerm（systemctl disable）脚本
- [x] 1.6 实现 data_dirs 支持：在 postinst 中生成 `mkdir -p` 命令
- [x] 1.7 组装 .deb：debian-binary + control.tar.gz + data.tar.gz 用 `ar` 打包，输出 `<name>_<version>_<arch>.deb`

## 2. 导出入口

- [x] 2.1 创建 `build/defs.bzl`：从 `build/deb.bzl` 导入并重导出 `flange_deb`

## 3. rootfs_customize 集成

- [x] 3.1 修改 `build/rootfs_customize.bzl`：新增 `custom_deb_targets` 属性（label_list, allow_files=[".deb"]），将 .deb 路径通过 `ROOTFS_DEB_TARGETS` 环境变量传递给 script
- [x] 3.2 修改 `rootfs/rockchip/build_customize.sh`：新增安装 `ROOTFS_DEB_TARGETS` 中 .deb 文件的逻辑（复制到 chroot、dpkg -i）
- [x] 3.3 修改 `rootfs/rockchip/BUILD.bazel`：在 `rootfs_customize` 中添加 `custom_deb_targets` 声明 `//app/adbd:adbd-deb`（通过 board select）

## 4. 验证

- [x] 4.1 验证 `bazel build //app/adbd:adbd-deb` 成功产出 .deb 文件，检查 deb 内容结构（ar t、tar tzf）（注: 宿主机无 Bazel，已完成静态验证：Starlark 语法、参数兼容性、rootfs 集成完整性、shell 语法）
