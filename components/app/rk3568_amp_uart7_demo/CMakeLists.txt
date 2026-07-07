# rk3568_amp_uart7_demo — Orange Pi CM4 AMP 协处理器固件（裸机 HAL）。
#
# 基于 rk3568_amp_demo，保留 Linux↔AMP rpmsg echo 行为，仅把从核 console
# 从 UART4_M1 切到 Orange Pi CM4 40pin 可引出的 UART7_M2。

cmake_minimum_required(VERSION 3.16)
project(rk3568_amp_uart7_demo C ASM)

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
