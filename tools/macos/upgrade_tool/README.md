# macOS upgrade_tool

本目录收录 Luckfox 官方附件中的 Rockchip `upgrade_tool v2.44`，用于
`flange flash` 的 Rockchip 宿主刷写。通用 Mach-O 二进制同时包含 Intel x86_64 与
Apple Silicon arm64；文件头声明的最低系统分别为 macOS 10.15 与 11.0。
安装、检查命令与验证范围见 [Rockchip 宿主工具说明](../../../docs/platforms/rockchip.md#宿主-upgrade_tool)。

[manifest.json](manifest.json) 固定 Luckfox 仓库提交、ZIP 下载地址、Git blob（文件对象）
摘要、压缩包 SHA256 与逐文件 SHA256。压缩包已与 Luckfox 官方 Git 对象核对，
SHA256 还与 JetKVM 官方同名发布附件提供的摘要一致；具体来源均在清单中。

二进制、配置、修订记录与 PDF 保持上游内容；解压时将 ZIP 的 GBK 中文文件名还原为
`命令行开发工具使用文档.pdf`，并恢复二进制的可执行权限。配置项均为注释。
可执行文件由 Git LFS（大文件存储）管理，需完成 `git lfs pull` 后使用。

这些文件为 Rockchip 第三方材料，不适用 flange 的 Apache-2.0。
原始压缩包未随附独立 LICENSE，保留原始 PDF 与修订记录，不推定其为开源软件；
参见[许可说明](../../../docs/licensing.md)。
