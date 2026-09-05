# 验证记录

## 最终验证结果

`builder/file_tree.py` 已通过 `os.readlink` 保留原始链接文本，App 和 Package 的相关复制路径与配方指纹已接入。

`radxa-rock5b-desktop-debug` 的完整 retry 已成功退出，耗时 29 分 33 秒，完成 6 个阶段、复用 2 个阶段。
产物发布到 `.build/target/radxa-rock5b/desktop/debug/`；终端日志为
`/tmp/flange-rock5b-desktop-debug-retry.log`，完整命令日志为该 target 的 `build.log`。
最终 raw/GPT、所有写入区域、rootfs、recovery、boot 和全部 manifest 的独立只读校验均已通过。

| 最终产物验收 | 结果 | 证据 |
| --- | --- | --- |
| raw 镜像与 GPT | raw 为 4,916,772,864 字节；GPT 有效；两个 bootloader 区域与 boot/recovery/rootfs 三个分区逐字节等于输入镜像 | `/tmp/flange-rock5b-image-verification.log` |
| 组件及 App 清单 | 8 个组件 manifest 全部有效；当前 AppBuildReport 包含 13 个资源 | `/tmp/flange-rock5b-manifest-verification.json` |
| rootfs 文件系统与内容 | e2fsck 通过、label 为 rootfs、状态 clean；1,212 条包记录一致；sudo `04755`、默认用户 UID/GID `1000:1000`、`/tmp` 为 `01777` | `/tmp/flange-rock5b-rootfs-verification.log` |
| MPP 运行包进入 rootfs | 按当前 manifest 声明的 runtime DEB 核对；两个实际库文件与 DEB/发布 install/镜像逐字节一致，两个 `.so.1 → .so.0` 链接与 DEB 一致 | `/tmp/flange-rock5b-rootfs-verification.log` |
| recovery 与 boot | 两个 ext4 均通过 e2fsck；recovery 的 134 条包记录、metadata、冻结配置、fstab 一致；双 extlinux 配置与内核/DTB/overlay 引用文件一致 | `/tmp/flange-rock5b-recovery-verification.log` |

运行包核验使用 `apps/<resource-id>/artifacts/` 中由当前 manifest 声明的 DEB，不读取旧 `target/app` 残留。
安装树包含的无版本 `.so` 开发链接不属于 runtime DEB，因此设备 rootfs 只按实际运行包内容验收。
最终额外通过 `AppBuildReport.runtime_debs_for(['rkmm-mpp'])` 核对报告运行包集合与实际已逐字节验收的 DEB 集合完全相同。
该请求报告身份为 `fb64bb5c9e3c3a8b6fcab7d49d680685fab78177635aa60cdcb98b663d058af5`。

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| App 构建、来源、编译、收集、配置、CLI、复制、缓存、multimedia 与 DEB 共 10 个测试文件 | 294 passed，1.82 秒；包含 App 发布的真实 I/O 故障注入回归 | `/tmp/flange-app-symlink-related-tests.log` |
| OpenSpec 治理测试 | 136 passed，0.14 秒 | `/tmp/flange-app-symlink-governance.log` |
| 本轮指定 5 个实现与测试文件的 Ruff `E4,E7,E9,F` | 通过 | 本轮静态检查结果 |
| 当前变更 `openspec validate fix-app-symlink-publication --strict` | 通过 | 本轮严格规格校验 |
| 主规格同步后 `openspec validate --all --strict` | 79 passed，0 failed | `/tmp/flange-app-symlink-final-strict.log` |
| 主规格同步后 `tests/openspec` | 136 passed，0.10 秒 | `/tmp/flange-app-symlink-final-governance.log` |
| 归档后 `openspec validate --all --strict` | 78 passed，0 failed；活动变更减少 1 项 | `/tmp/flange-app-symlink-archived-strict.log` |
| 归档后 `tests/openspec` | 136 passed，0.09 秒 | `/tmp/flange-app-symlink-archived-governance.log` |
| 真实 Docker 中的 `rkmm-mpp` 重新构建与发布 | 成功，2 分 36 秒 | `/tmp/flange-rock5b-desktop-debug-retry.log` |
| 已发布 MPP 的链接与 manifest 检查 | manifest 有效；4 个链接目标准确，两个实际库文件存在；DEB 为 1,089,374 字节 | `/tmp/flange-mpp-publication-verification.json` |
| 真实 Docker 共享卷 fixture 集成 | `test_app_symlink_storage_docker.py`：1 passed，2.13 秒；默认不启用 Docker 测试时为 1 skipped | `/tmp/flange-app-symlink-storage-docker.log` |
| 真实 MPP stage、已发布 install 与 helper 共享卷副本三方对照 | 39 条记录、4 个链接、目录摘要完全一致；已发布与复制后的 manifest 均有效 | `/tmp/flange-mpp-file-tree-fixed-probe.log` |

MPP 的已验证产物身份为
`43dadb7a4da592ecc08e7430842bc73ca552490333cfb4ff320a5ef17f3d8a05`。
已发布链接为 `librockchip_mpp.so → librockchip_mpp.so.1 → librockchip_mpp.so.0` 与
`librockchip_vpu.so → librockchip_vpu.so.1 → librockchip_vpu.so.0`。

三方对照的安装树 SHA-256 为
`c6f3b74b4251864ad63aece4ddc4acb41b95588797fe3266d3721d626040123b`。
这个值是安装树摘要，与上文包含完整输出集合的产物身份不同。

共享卷 fixture 覆盖链式链接、永久悬空链接及带 `./`、重复斜杠和尾斜杠的原始目标文本，
并检查普通文件/目录模式、空目录、源树未改动、树摘要与 manifest 身份一致。
宿主链接实际带 `com.apple.provenance` 与无害的 `user.flange-copy-test` 属性；
容器可见前者，修复后复制不对链接执行扩展属性写入。可用以下命令重现：

```bash
FLANGE_RUN_DOCKER_TESTS=1 .venv/bin/python -m pytest \
  tests/integration/test_app_symlink_storage_docker.py -q
```

本次 retry 完成 App 闭包后继续完成 boot、rootfs、recovery 和 image；image 日志记录了
4689 MiB 空镜像创建、GPT 与五个区域写入；随后独立产物校验已确认这些区域与输入镜像一致。

## 已确认的失败边界

真实 `radxa-rock5b-desktop-debug` 在 `rkmm-mpp` 编译与打包后，复制安装树时失败。根因对照证据：
`/tmp/flange-app-symlink-storage-probe.log`。

- 同一真实 stage 的动态库目录使用 `shutil.copytree(..., symlinks=True)` 复制到 Linux `overlayfs` 成功；复制到宿主共享 `fuseblk` 卷的新目录时，三条动态库链接复制报 `ENOENT`。
- 失败调用链为 `shutil.copystat → _copyxattr → os.setxattr(..., follow_symlinks=False)`。源链接存在 11 字节的 `com.apple.provenance` 扩展属性。
- 对共享卷新建的悬空链接写入该属性返回 `ENOENT`；目标落地后，同一操作成功。链接自身的 `utime(..., follow_symlinks=False)` 在两种状态下均成功。
- 初始探针改为复制链接文本及普通对象元数据后，38 个目录项与源树相符，容器退出码为 0；生产修复随后通过上文真实 MPP 三方对照和完整镜像验收。

## 验收范围

本次完成容器构建、共享卷复制、发布清单和最终镜像的只读验证。未连接或刷写板卡；
不把镜像构建成功等同于板卡启动、桌面显示或外设实机验收。

两份 delta 已逐字同步到主规格，7 项任务全部完成；变更归档为
`2026-09-05-fix-app-symlink-publication`。归档前后 `git diff --check` 均通过。
