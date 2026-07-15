## 1. YT8512C 初始化补丁

- [x] 1.1 新增 ATK-RK3506B board kernel patch：修复 LED1 扩展寄存器地址，提取共用 LED/auto-sleep 初始化，并为 PHY ID `0x00000128` 增加独立的 BSP 顺序 config_init 与受轮询保护的双 software reset
- [x] 1.2 保留 PHY ID `0x00000118` 的 clock init，确保 `0x00000128` 不改写 `0x0050`/`0x4000`，且不照搬 BSP 的 `PHY_POLL` driver flags

## 2. 自动化验证

- [x] 2.1 增加板级静态回归测试，覆盖 LED1 地址、两型号 config_init 路由、reset 顺序、callbacks 与禁止项
- [x] 2.2 执行 patch 可应用性检查、相关 pytest、`git diff --check` 与 OpenSpec strict validate
- [x] 2.3 在 Docker 中强制重建 ATK-RK3506B kernel，确认 `motorcomm.o`、目标 DTB 与 `boot.img` 生成

## 3. 实机验收

- [x] 3.1 刷入新 `boot.img` 并断电冷启动，分别验证 `end0`/`end1` 的 PHY 绑定、carrier、Link Up/Down 与连续网线插拔，不执行手工 MDIO reset
