# QDL 宿主刷写工具

本目录收录 Arduino `qdl-packing v2.4-26` 的官方预编译工具，供 UNO Q 的
`flange flash` 使用。`arm64/` 和 `x86_64/` 按宿主 CPU 架构自动选择。
无需安装 QDL，也无需重新构建 Docker。二进制保持上游原样，保留可执行权限。
二进制由 Git LFS 管理；克隆后需确保已安装 Git LFS 并执行 `git lfs pull`。

- 发布来源：https://github.com/arduino/qdl-packing/releases/tag/v2.4-26
- 打包源码：https://github.com/arduino/qdl-packing/tree/81e410a3f6b86b86531e713acf87188ee9a583bf
- QDL 源码：https://github.com/linux-msm/qdl/tree/v2.4
- 每个架构目录的 `manifest.json` 记录下载地址、发布包 SHA256 和入库文件 SHA256。
  下载后已与 GitHub Release 提供的摘要比对。
- QDL 使用 BSD-3-Clause；各架构目录保留官方随附的 `LICENSE` 与 `README.upstream.md`。
  静态链接依赖沿用各自许可证，具体依赖与补丁见上游打包配方；不适用 flange 根目录许可。

官方工具 `--version` 输出 `v2.4-dirty`，来自上游 v2.4 加 Arduino 打包补丁，
不表示 flange 修改过二进制。发布版本以 `manifest.json` 的 `v2.4-26` 为准。
Linux 版本依赖 glibc，不能按 musl 静态程序使用；macOS 版本使用系统框架。

工具选择顺序为本目录的本地覆盖文件 `qdl`、匹配架构子目录中的 `qdl`、PATH。
更新时四个版本一起更新，重新比对官方发布摘要并更新每个架构的 manifest，
保留许可证，再运行 `tests/test_unoq_tools.py` 与 `tests/test_unoq_flash.py`。
