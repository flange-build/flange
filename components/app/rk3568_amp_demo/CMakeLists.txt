# rk3568_amp_demo — AMP 协处理器固件（裸机 HAL）。
#
# 这是 flange 的 amp 类型 app：自己的 CMake 工程，引用 components/amp 的 HAL SDK
# （通过 rockchip-hal.cmake）。SDK 只读引用、不被改、不在 SDK 里就地构建。
#
# rockchip-hal.cmake 由 flange amp 组件（builder/platforms/rockchip/amp.py）以
# -DCMAKE_TOOLCHAIN_FILE=<hal>/rockchip-hal.cmake 传入（提供裸机工具链 +
# rockchip_hal_target 函数）；内存布局 / SoC / CPU 由 amp 组件经 -DROCKCHIP_AMP_*
# 传入（单一事实源 = config.amp.memory，勿在此硬编）。
#
# 产物：firmware(.elf) + firmware.bin；amp 组件取 firmware.bin → mkimage → amp.img。

cmake_minimum_required(VERSION 3.16)
project(rk3568_amp_demo C ASM)

add_executable(firmware
    src/main.c)

rockchip_hal_target(firmware
    SOC              ${ROCKCHIP_AMP_SOC}
    CPU              ${ROCKCHIP_AMP_CPU}
    FIRMWARE_BASE    ${ROCKCHIP_AMP_FIRMWARE_BASE}
    DRAM_SIZE        ${ROCKCHIP_AMP_DRAM_SIZE}
    SHMEM_BASE       ${ROCKCHIP_AMP_SHMEM_BASE}
    SHMEM_SIZE       ${ROCKCHIP_AMP_SHMEM_SIZE}
    LINUX_RPMSG_BASE ${ROCKCHIP_AMP_LINUX_RPMSG_BASE}
    LINUX_RPMSG_SIZE ${ROCKCHIP_AMP_LINUX_RPMSG_SIZE})
