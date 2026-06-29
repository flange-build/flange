## ADDED Requirements

### Requirement: 容器内必须具备裸机 ARM 工具链

Docker 构建容器（`docker/Dockerfile` 构建出的 `build` service 镜像）SHALL 预装 newlib 版裸机 ARM 工具链 `arm-none-eabi-`（提供 `--specs=nosys.specs`/`--specs=nano.specs`），使 amp 协处理器固件（Cortex-A55 AArch32 裸机 HAL 与 RT-Thread）可在容器内直接编译。版本 SHALL 钉定为 gcc-10（与 flange 既有 u-boot/kernel 的 gcc-10 约定一致，规避 gcc-13 在 Rockchip 低层代码上的隐蔽 miscompile 风险）。现有的 glibc 交叉工具链（`aarch64-linux-gnu-`、`arm-linux-gnueabihf-`）面向 Linux 用户态、不提供 nosys spec，SHALL NOT 用于裸机固件编译。

#### Scenario: 容器内可直接调用 arm-none-eabi-gcc

- **WHEN** 在 `build` 容器内执行 `which arm-none-eabi-gcc` 与 `arm-none-eabi-gcc --version`
- **THEN** 返回非空路径与版本号，退出码为 0
- **AND** 版本号主版本为 10

#### Scenario: 裸机最小程序可用 nosys spec 链接通过

- **WHEN** 在 `build` 容器内用 `arm-none-eabi-gcc --specs=nosys.specs -mcpu=cortex-a55 -mfloat-abi=hard` 编译一个最小裸机 C 程序
- **THEN** 编译链接成功，产物 `file` 输出包含 `ARM`（非 Linux 动态可执行）

#### Scenario: glibc 工具链不被用于裸机固件

- **WHEN** amp 构建器在容器内编译固件
- **THEN** 使用 `arm-none-eabi-` 前缀工具链，而非 `arm-linux-gnueabihf-`/`aarch64-linux-gnu-`
