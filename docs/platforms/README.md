# 平台索引

平台定义芯片家族共用的构建与刷写策略；板卡定义接线、存储、产品和功能选择。
先查[板卡索引](../boards/README.md)，不要把平台能力当作所有硬件的验收结论。

| 平台标识 | SoC 范围 | 启动 / 刷写 | 详细说明 |
| --- | --- | --- | --- |
| `rockchip` | RV1106、RK3506B、RK3566/3568/3576/3582/3588/3588S | U-Boot / upgrade_tool | [Rockchip](rockchip.md) |
| `amlogic` | S905Y2、S905D3、A311D | U-Boot / pyamlboot + fastboot | [Amlogic](amlogic.md) |
| `allwinnera733` | A733 | U-Boot / 块设备写入 | [Allwinner A733](allwinnera733.md) |
| `qualcommqcs6490` | QCS6490 | UEFI/GRUB / edl-ng | [QCS6490](qualcommqcs6490.md) |
| `qualcommsc8280xp` | SC8280XP | UEFI/GRUB / edl-ng | [SC8280XP](qualcommsc8280xp.md) |
| `qualcommqrb2210` | QRB2210 | ABL/U-Boot/systemd-boot / QDL | [Arduino UNO Q](../boards/arduino-uno-q.md) |
| `nvidiategra186` | Tegra186 | NVIDIA 启动链 / tegraflash | [NVIDIA TX2](nvidiategra186.md) |

镜像布局、扇区单位、分区清单及刷写边界见[启动、镜像与刷写](../boot-and-flash.md)。
添加平台见[扩展指南](../extension-guide.md)。
