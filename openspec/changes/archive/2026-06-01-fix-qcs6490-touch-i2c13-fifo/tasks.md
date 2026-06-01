## 1. 编写内核 patch 0006

- [x] 1.1 基于 `.build/sources/repos/kernel/drivers/i2c/busses/i2c-qcom-geni.c`（7.0.2）现状，写 `components/platform/qualcommqcs6490/patches/kernel/0006-i2c-geni-force-fifo-on-gsi-mismatch.patch`：在 probe 的 `proto` 判断（`proto==GENI_SE_INVALID_PROTO` / `proto!=GENI_SE_I2C`）后追加第三分支——`proto==GENI_SE_I2C` 且 `!device_property_read_bool(dev,"qcom,enable-gsi-dma")` 且 `readl_relaxed(se.base+GENI_IF_DISABLE_RO)&FIFO_IF_DISABLE` 时，重调 `geni_load_se_firmware(&gi2c->se, GENI_SE_I2C)`，失败 `dev_err_probe + goto err_resources`，附解释性注释
- [x] 1.2 patch header 写中文 commit message（根因＝bootloader 预 provision SE5 GSI + proto 守卫跳过重载致 0003 失效；方案＝失配时重 provision 回 FIFO；引用根因记忆 `qcs6490-touch-i2c13-gsi-fifo`），确认 diff 仅动 `i2c-qcom-geni.c`、上下文行严格匹配 7.0.2 源码（`git apply --check` 零 fuzz 命中 1078）

## 2. 纳入构建并编译

- [x] 2.1 查 `builder/platforms/qualcommqcs6490/kernel.py` 的 patch 应用机制（base.py:77 `sorted(glob("*.patch"))` + base.py:81 `git apply`，失败回退 `patch -p1`），确认 `0006` 自动纳入按序 `0001–0006`、无需登记；`git apply --check` 零 fuzz
- [x] 2.2 `flange build kernel`（用户已编译）：产出 `Image`(#14) 与 `i2c-qcom-geni.ko`，源码树 line 1082 已含 0006 分支
- [x] 2.3 验证编出的 `i2c-qcom-geni.ko` 确含新分支：标记字符串 `i2c FIFO re-provision failed ret: %d` 在、未定义符号 `U geni_load_se_firmware` 在、vermagic `7.0.2+ ... aarch64` 与设备匹配

## 3. 最小验证（不刷机，实机已通过）

- [x] 3.1 ⚠️ **热插不可行（重要发现）**：`rmmod i2c_qcom_geni` 会扯崩挂在 i2c-13 的背光(sgm37604a)→panel→DRM，触发内核 Oops×2（`drm_self_refresh_helper`），模块卡死 `-1`、需重启恢复。**改用**：把新 `i2c-qcom-geni.ko.zst` 覆盖 `/lib/modules/7.0.2+/.../`（备份 `.bak-13`）+ 重启，让开机加载新模块（`CONFIG_MODULE_SIG` 未开、免签名）
- [x] 3.2 实机验证通过：`GPI transfer failed` 48→**0**、`Error in Transaction` 48→**0**、`sec_ts_read_device_id` `0,0,0`→**`AC,6F,70`**、完整信息 `nT:12 nR:20 Tx:18 Rx:32 1080×2160`、触摸 **IRQ 0→430 + evtest 识别坐标**、`i2c10` RTC `15:01:20` 不回归、零 oops；背光寄存器写入也恢复（brightness=2048）

## 4. 整机刷写实板验证（对照 spec scenario）

- [ ] 4.1 正式 `flange flash` `radxa-dragon-q6a-meizu-e3-bringup-*` 完整镜像（生产部署）；**验证阶段已用手动部署等效达成**（换 `/lib/modules` 模块+`/boot/vmlinuz`+重启，实机 boot 新内核#14+补丁模块）
- [x] 4.2 spec 场景"i2c13 走 FIFO、无 GPI DMA 传输失败"已实机通过：device id `AC,6F,70`、`GPI transfer failed`=0、触摸响应（IRQ 430+evtest 坐标）、背光 brightness=2048
- [x] 4.3 回归验证通过：`i2c10` RTC 读 `15:01:20` 正常、无内核 oops（`default` 产物 i2c13 无从机、本就不触发该分支）

## 5. 文档与规格更正

- [x] 5.1 更正 `wiki/boards/radxa-dragon-q6a.md` 坑#11（追加"7.0.2 更正"块：proto 守卫根因 + 0006 方案 + 实机结果 + 热插坑）；frontmatter sources 补 0006；log.md 追加 sync 条目
- [x] 5.2 复核 spec delta 两个 MODIFIED requirement 与实现一致（patch 序列 `0001–0006`、`i2c13` FIFO 重 provision 机制 `device_property_read_bool`+`FIFO_IF_DISABLE`、触发仅命中 i2c13、i2c10/default 不回归）

## 6. 收尾

- [x] 6.1 `openspec validate` 通过；按 ProjectSpec §10.1 建 `fix/qcs6490-touch-i2c13-fifo` 分支，§10.3 拆两 commit：`fe35a05` fix(qcs6490) 修复+change、`f84bdc2` docs(wiki) 坑#11
- [x] 6.2 运行 `/opsx:archive` 归档本 change（实板验证已通过）
