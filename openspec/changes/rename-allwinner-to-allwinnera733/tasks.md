## 1. 前置条件

- [x] 1.1 运行 `openspec list`，确认 `add-shared-repo-references` 不在未归档列表中；若仍未归档，先完成 `/opsx:apply add-shared-repo-references` 与 `/opsx:archive add-shared-repo-references`，避免两份未归档变更同时修改 `allwinner-platform` capability
- [x] 1.2 确认工作树干净（`git status` 无未提交改动），便于后续 `git mv` 提交独立成形
- [x] 1.3 全文 grep 盘点 `"allwinner"` 字面量与 `\ballwinner\b` 目录引用（已在 proposal 阶段列出，此处按最新工作树再确认一遍），产出待改清单

## 2. 平台配置目录搬家（git mv 提交）

- [x] 2.1 `git mv platform/allwinner platform/allwinnera733`
- [x] 2.2 `git mv builder/platforms/allwinner builder/platforms/allwinnera733`
- [x] 2.3 提交"rename: allwinner → allwinnera733 目录搬家"，保持该 commit 仅含 rename，不混入内容修改

## 3. 配置与字面量改写

- [x] 3.1 修改 `platform/allwinnera733/config.py`：`PLATFORM.vendor` 从 `"allwinner"` 改为 `"allwinnera733"`
- [x] 3.2 修改 `platform/allwinnera733/a733/config.py`：`SOC.platform` 从 `"allwinner"` 改为 `"allwinnera733"`
- [x] 3.3 修改 `board/radxa-cubie-a7z/config.py`：`BOARD.platform` 从 `"allwinner"` 改为 `"allwinnera733"`

## 4. 构建器类名与 flash 注册键改写

- [x] 4.1 重命名类：`AllwinnerKernelBuilder` → `AllwinnerA733KernelBuilder`（`builder/platforms/allwinnera733/kernel.py`）
- [x] 4.2 重命名类：`AllwinnerBootloaderBuilder` → `AllwinnerA733BootloaderBuilder`（`bootloader.py`）
- [x] 4.3 重命名类：`AllwinnerRootfsBuilder` → `AllwinnerA733RootfsBuilder`（`rootfs.py`）
- [x] 4.4 重命名类：`AllwinnerBootBuilder` → `AllwinnerA733BootBuilder`（`boot.py`）
- [x] 4.5 重命名类：`AllwinnerImageBuilder` → `AllwinnerA733ImageBuilder`（`image.py`）
- [x] 4.6 更新 `builder/platforms/allwinnera733/__init__.py`：`create_builder` 中的 import 路径（`builder.platforms.allwinner.xxx` → `builder.platforms.allwinnera733.xxx`）和类名引用
- [x] 4.7 修改 `builder/flash.py`：`AllwinnerFlashStrategy` 类名改为 `AllwinnerA733FlashStrategy`
- [x] 4.8 修改 `builder/flash.py`：`_FLASH_STRATEGIES` 注册表键 `"allwinner"` 改为 `"allwinnera733"`

## 5. 代码内注释与日志字面量同步

- [x] 5.1 `builder/platforms/allwinnera733/kernel.py` 中注释引用的 `platform/allwinner/a733/config.py` 改为 `platform/allwinnera733/a733/config.py`
- [x] 5.2 其余代码文件内注释、docstring、错误信息里出现的"Allwinner 平台"/`allwinner` 字面量：若特指 flange 平台标识符，同步改为 `allwinnera733`；若指厂商/SoC 家族自然语义，保留原文
- [x] 5.3 提交"rename: 配置、类名、注册键同步到 allwinnera733"

## 6. 构建验证

- [ ] 6.1 清空 `output/radxa-cubie-a7z-default-debug/` 和 `cache/` 中该 target 相关缓存，迫使从头构建
- [ ] 6.2 执行 `flange lunch radxa-cubie-a7z-default-debug` 与 `flange build`，确认完整构建成功、无 `未发现平台：allwinnera733` 或 `不支持的平台` 类错误
- [ ] 6.3 检查生成的 `output/radxa-cubie-a7z-default-debug/flash-config.json`：`platform` 字段为 `"allwinnera733"`，分区表、pre_flash、flash_tool 与旧版一致
- [ ] 6.4 物理 SD 卡刷写并上机启动 A7Z，验证 kernel console、rootfs 登录、USB adbd（`adb shell`）可用（平行于已归档 change `ceed497 feat(allwinner): A7Z 默认启用 adbd 调试通道` 的验收）

## 7. 文档与 OpenSpec 元数据

- [x] 7.1 `ProjectSpec.md`：仅更新明确指向 flange 平台标识符的字面量（路径、代码引用），厂商名保留（该文档仅有厂商自然语义的"Allwinner"，无需改动）
- [x] 7.2 `roadmap.md`：同上原则更新（已更新 `builder/platforms/allwinner/` → `builder/platforms/allwinnera733/`）
- [x] 7.3 `openspec/flange-build-tool-design.md`：同上原则更新（该文档仅有厂商自然语义的"Allwinner"，无需改动）
- [x] 7.4 `CLAUDE.md`：检查无引用，无需改动（验证确认）（仅厂商自然语义"Allwinner"，保留）

## 8. OpenSpec 校验与归档

- [ ] 8.1 运行 `openspec validate rename-allwinner-to-allwinnera733`，确保所有 delta 语法正确
- [ ] 8.2 运行 `openspec diff --change rename-allwinner-to-allwinnera733` 复核：新增 `allwinnera733-platform` / `allwinnera733-flash`，删除 `allwinner-platform` / `allwinner-flash`，`platform-abstraction` 中三条 scenario 文本更新
- [ ] 8.3 `git log --name-status` 校验 git 重命名检测生效（`R100` 或接近满分），本次改名不应出现大量"add + delete"
- [ ] 8.4 所有任务完成后执行 `/opsx:archive rename-allwinner-to-allwinnera733`
