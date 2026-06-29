# rockchip-hal.cmake — Rockchip HAL 裸机 SDK 的 CMake 接口
#
# 供 components/app 下的 amp 类型 app（裸机 HAL 协处理器固件）引用。SDK
# （components/amp/rockchip/hal）本身是 Makefile 体系、不是 CMake-native，本文件
# 把它桥接成 app 可直接 include 的 CMake 接口——app 只写自己的 main.c，其余
# （HAL 驱动 / CMSIS 启动 / BSP / rpmsg-lite / 裸机工具链 / 链接脚本）由本文件提供。
# SDK 只读引用，不被 app 修改、也不在 SDK 里就地构建。
#
# 提供：
#   - 裸机 ARM 工具链（arm-none-eabi）+ Cortex-A55 AArch32 编译/链接 flag；
#   - rockchip_hal_target() 函数：给一个 executable target 挂上 HAL/CMSIS/BSP/
#     rpmsg-lite 源 + include + 内存布局宏 + 预处理后的链接脚本 + 生成 .bin。
#
# 用法（app 的 CMakeLists.txt）：
#   cmake_minimum_required(VERSION 3.16)
#   # 作工具链文件传入（flange amp 组件以 -DCMAKE_TOOLCHAIN_FILE=<hal>/rockchip-hal.cmake
#   # 调用），或在 project() 前 include() 本文件。
#   project(rk3568_amp_demo C ASM)
#   add_executable(firmware src/main.c)
#   rockchip_hal_target(firmware
#       SOC RK3568 CPU 3                       # SoC 名（= lib/CMSIS/Device/<SOC>）+ 从核 mpidr index
#       FIRMWARE_BASE 0x07000000 DRAM_SIZE 0x00800000
#       SHMEM_BASE 0x07800000 SHMEM_SIZE 0x00400000
#       LINUX_RPMSG_BASE 0x07c00000 LINUX_RPMSG_SIZE 0x00500000)
#   # → 产出 firmware（可执行）+ firmware.bin；amp 组件再 mkimage 打成 amp.img
#
# 注：内存布局（FIRMWARE_BASE 等）是 flange 的单一事实源（config.amp.memory），
# 由 amp 组件经 -D 传给 app 的 CMakeLists、再传给本函数——勿在 app 里硬编。
# app 的 src/ 必须自带 hal_conf.h / middleware_conf.h（决定启用哪些 HAL 模块），
# 可参考 SDK project/<soc>/src 的同名文件改写。
#
# 能力边界：本接口提供 HAL 驱动 + CMSIS（启动/system/mmu）+ BSP + rpmsg-lite 核心，
# 不含 unity/test、benchmark/coremark、sdhci——app 如需可自行在 CMakeLists 追加。
# SoC：rk3566 须传 SOC RK3568（SDK 的 lib/CMSIS/Device、lib/bsp、rpmsg porting 下
# 只有 RK3568，rk3566 同 die 复用之）；CPU flag 写死 cortex-a55+crypto（rk356x/
# rk3588 全 A55 可复用）。产物：${target}（可执行，无 .elf 后缀）+ ${target}.bin
# 落在 CMAKE_CURRENT_BINARY_DIR；amp 组件取该 .bin 去 mkimage 打 amp.img（本文件
# 不做 mkimage、不碰分区）。

# --- HAL SDK 根（本文件所在目录）---
get_filename_component(ROCKCHIP_HAL_ROOT "${CMAKE_CURRENT_LIST_DIR}" ABSOLUTE)

# --- 裸机工具链（须在 project() 前生效；作工具链文件或 include() 均可）---
# 容器内官方 gcc-arm-none-eabi-10（docker/Dockerfile 安装、软链进 /usr/local/bin），
# 提供 newlib 的 --specs=nosys.specs。
set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_SYSTEM_PROCESSOR arm)
set(CMAKE_C_COMPILER   arm-none-eabi-gcc)
set(CMAKE_ASM_COMPILER arm-none-eabi-gcc)
set(CMAKE_OBJCOPY      arm-none-eabi-objcopy CACHE FILEPATH "objcopy")
# 裸机：编译器自检不要求能链接出完整可执行（无 libc/启动文件），用静态库探测。
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

# 误用守卫：本文件须作 CMAKE_TOOLCHAIN_FILE 或在 project() 之前 include()——
# 否则上面的工具链设置在 C 语言已 enable 后会被静默忽略（编译器探测已发生）。
if(CMAKE_C_COMPILER_LOADED)
    message(WARNING "rockchip-hal.cmake 须作 CMAKE_TOOLCHAIN_FILE 或在 project() 前 "
        "include()；当前 C 语言已启用，工具链设置已被忽略，链接极可能失败。")
endif()

# --- rockchip_hal_target(<target> SOC <soc> CPU <id> [PROJECT <dir>] <mem...>) ---
function(rockchip_hal_target target)
    set(_one SOC CPU PROJECT
             FIRMWARE_BASE DRAM_SIZE SHMEM_BASE SHMEM_SIZE
             LINUX_RPMSG_BASE LINUX_RPMSG_SIZE)
    cmake_parse_arguments(HAL "" "${_one}" "" ${ARGN})
    if(NOT HAL_SOC)
        message(FATAL_ERROR "rockchip_hal_target: 必须指定 SOC（如 RK3568）")
    endif()
    string(TOLOWER "${HAL_SOC}" _soc_lc)
    if(NOT HAL_PROJECT)
        set(HAL_PROJECT "${_soc_lc}")   # 链接脚本所在 project 目录，默认 = 小写 SoC
    endif()
    set(_hal "${ROCKCHIP_HAL_ROOT}")

    # --- 参数防呆：缺内存布局/非法 CPU 会让链接脚本 ORIGIN/LENGTH 为空、或产坏宏
    #     → ld 晦涩报错。前移成 configure 期清晰错误（内存布局由 flange
    #     config.amp.memory 单一事实源经 -D 传入，无 SDK 的 ?= 兜底）。
    foreach(_v FIRMWARE_BASE DRAM_SIZE SHMEM_BASE SHMEM_SIZE
               LINUX_RPMSG_BASE LINUX_RPMSG_SIZE)
        if("${HAL_${_v}}" STREQUAL "")
            message(FATAL_ERROR "rockchip_hal_target: 缺内存布局参数 ${_v}"
                "（应由 flange config.amp.memory 经 -D 传入）")
        endif()
    endforeach()
    if(NOT "${HAL_CPU}" MATCHES "^[0-3]$")
        message(FATAL_ERROR "rockchip_hal_target: CPU 须为 0/1/2/3，当前 '${HAL_CPU}'")
    endif()

    # --- 源：HAL 驱动（含子目录一层）+ BSP + CMSIS 启动/system + rpmsg-lite ---
    # .c 与 .S 都收（等价 SDK 的 *.[cS]）：lib/hal/src/hal_smccc_gcc.S 定义
    # HAL_SMCCC_Call（AArch32 smc #0），被 hal_smccc.c/hal_ddr_ecc.c 引用——漏 .S
    # 会链接 undefined reference。
    file(GLOB _hal_src
         "${_hal}/lib/hal/src/*.c" "${_hal}/lib/hal/src/*.S"
         "${_hal}/lib/hal/src/*/*.c" "${_hal}/lib/hal/src/*/*.S")
    file(GLOB _bsp_src
         "${_hal}/lib/bsp/${HAL_SOC}/*.c" "${_hal}/lib/bsp/${HAL_SOC}/*.S")
    file(GLOB _cmsis_src
         "${_hal}/lib/CMSIS/Device/${HAL_SOC}/Source/Templates/*.c"
         "${_hal}/lib/CMSIS/Device/${HAL_SOC}/Source/Templates/GCC/*.c"
         "${_hal}/lib/CMSIS/Device/${HAL_SOC}/Source/Templates/GCC/*.S")
    set(_rpmsg "${_hal}/middleware/rpmsg-lite/lib")
    file(GLOB _rpmsg_src
         "${_rpmsg}/common/*.c"
         "${_rpmsg}/rpmsg_lite/*.c"
         "${_rpmsg}/rpmsg_lite/porting/platform/${HAL_SOC}/*.c"
         "${_rpmsg}/init/platform/${HAL_SOC}/*.c"
         "${_rpmsg}/virtio/*.c")
    list(APPEND _rpmsg_src
         "${_rpmsg}/rpmsg_lite/porting/environment/rpmsg_env_bm.c")
    target_sources(${target} PRIVATE
        ${_hal_src} ${_bsp_src} ${_cmsis_src} ${_rpmsg_src})

    # --- include（app 自己的 src 在前，供 hal_conf.h 等覆盖）---
    set(_incdirs
        ${CMAKE_CURRENT_SOURCE_DIR}/src
        ${_hal}/lib/hal/inc
        ${_hal}/lib/bsp/${HAL_SOC}
        ${_hal}/lib/CMSIS/Core_A/Include
        ${_hal}/lib/CMSIS/Device
        ${_hal}/lib/CMSIS/Device/${HAL_SOC}/Include
        ${_hal}/lib/CMSIS/Device/${HAL_SOC}/Source/Templates/GCC
        ${_rpmsg}/include
        ${_rpmsg}/include/environment/bm
        ${_rpmsg}/include/platform/${HAL_SOC})
    target_include_directories(${target} PRIVATE ${_incdirs})

    # --- CPU / 内存宏 / 从核宏（对齐 SDK Cortex-A.mk + project Makefile）---
    set(_cpu -mcpu=cortex-a55+crypto -mfloat-abi=hard -marm
             -ftree-vectorize -ffast-math)
    set(_mem -DFIRMWARE_BASE=${HAL_FIRMWARE_BASE} -DDRAM_SIZE=${HAL_DRAM_SIZE}
             -DSHMEM_BASE=${HAL_SHMEM_BASE} -DSHMEM_SIZE=${HAL_SHMEM_SIZE}
             -DLINUX_RPMSG_BASE=${HAL_LINUX_RPMSG_BASE}
             -DLINUX_RPMSG_SIZE=${HAL_LINUX_RPMSG_SIZE})
    # 共享内存由 CPU1（PRIMARY_CPU）初始化；其余核传 -DCPU<n>。
    if(HAL_CPU STREQUAL "1")
        set(_cpudef -DPRIMARY_CPU)
    else()
        set(_cpudef -DCPU${HAL_CPU})
    endif()
    target_compile_options(${target} PRIVATE
        ${_cpu} -O2 -g -nostartfiles -Wall -Wformat=2 -Wno-unused-parameter
        ${_mem} ${_cpudef}
        $<$<COMPILE_LANGUAGE:C>:-std=gnu99>
        $<$<COMPILE_LANGUAGE:C>:-Wstrict-prototypes>
        $<$<COMPILE_LANGUAGE:C>:-Wmissing-prototypes>
        $<$<COMPILE_LANGUAGE:ASM>:-D__ASSEMBLY__>)

    # --- 链接脚本：cpp 预处理 project 的 gcc_arm.ld.S（注入内存布局宏）---
    set(_ld_in "${_hal}/project/${HAL_PROJECT}/GCC/gcc_arm.ld.S")
    if(NOT EXISTS "${_ld_in}")
        message(FATAL_ERROR "找不到链接脚本: ${_ld_in}")
    endif()
    # per-target 命名，避免同一 CMakeLists 多个 amp target 的 OUTPUT 撞名。
    set(_ld_out "${CMAKE_CURRENT_BINARY_DIR}/${target}_gcc_arm.ld")
    # 跨 SoC：部分 SoC 的 gcc_arm.ld.S #include "hal_conf.h" 并用 SRAM_BASE 等宏，
    # 故预处理也带上 include（rk3568 的 ld.S 无 #include、只用 6 内存宏，带 -I 无害）。
    set(_ld_iflags)
    foreach(_d ${_incdirs})
        list(APPEND _ld_iflags "-I${_d}")
    endforeach()
    add_custom_command(OUTPUT ${_ld_out}
        COMMAND ${CMAKE_C_COMPILER} -E -P -x c ${_mem} ${_cpudef} ${_ld_iflags}
                ${_ld_in} -o ${_ld_out}
        DEPENDS ${_ld_in}
        COMMENT "预处理链接脚本 → ${target}_gcc_arm.ld（注入内存布局）"
        VERBATIM)
    add_custom_target(${target}_ldscript DEPENDS ${_ld_out})
    add_dependencies(${target} ${target}_ldscript)

    # --- 链接 flag（裸机 newlib：nosys specs + gc-sections + 链接脚本）---
    target_link_options(${target} PRIVATE
        ${_cpu} -nostartfiles -Wl,--gc-sections --specs=nosys.specs
        -T${_ld_out}
        -Wl,-Map=$<TARGET_FILE_DIR:${target}>/${target}.map,-cref)
    # -lm -lgcc 必须排在对象之后（GNU ld 单遍符号解析）——用 link_libraries 落到
    # <LINK_LIBRARIES>（对象之后），不要放 target_link_options（会排到对象之前）。
    target_link_libraries(${target} PRIVATE m gcc)
    set_target_properties(${target} PROPERTIES LINK_DEPENDS ${_ld_out})

    # --- 产出 .bin（amp 组件再 mkimage 用 amp_linux.its 打 amp.img）---
    add_custom_command(TARGET ${target} POST_BUILD
        COMMAND ${CMAKE_OBJCOPY} -R .note -R .note.gnu.build-id -R .comment -S
                -O binary $<TARGET_FILE:${target}>
                $<TARGET_FILE_DIR:${target}>/${target}.bin
        COMMENT "objcopy → ${target}.bin"
        VERBATIM)
endfunction()
