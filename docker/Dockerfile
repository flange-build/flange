FROM --platform=linux/amd64 ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Ubuntu noble sources 投放：主源限制 amd64，追加 ports.ubuntu.com 提供 arm64/armhf
# —— 不替换的话 dpkg --add-architecture arm64 之后 apt update 会对 archive.ubuntu.com
# 的 arm64 索引发 404（该镜像不托管 amd64/i386 之外的架构）。
COPY docker/apt/ubuntu.sources /etc/apt/sources.list.d/ubuntu.sources

# 基础构建工具 + aarch64 交叉编译工具链 + 内核/U-Boot 构建依赖
# + Allwinner U-Boot 构建依赖（32-bit ARM 工具链 + lib32 支持 Allwinner 专有工具）
# + C/C++ 构建系统（cmake/meson/ninja/pkg-config）与跨架构 dev 包骨架
#
# multiarch 启用必须在 apt-get update 之前完成，否则索引拉不全；
# 故将 dpkg --add-architecture 与 apt 操作合并到同一个 RUN 层。
RUN dpkg --add-architecture arm64 \
    && dpkg --add-architecture armhf \
    && apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc-aarch64-linux-gnu \
        g++-aarch64-linux-gnu \
        binutils-aarch64-linux-gnu \
        gcc-arm-linux-gnueabihf \
        g++-arm-linux-gnueabihf \
        binutils-arm-linux-gnueabihf \
        crossbuild-essential-armel \
        ca-certificates \
        curl \
        gnupg \
        git \
        openssh-client \
        python3 \
        python3-yaml \
        python3-pyelftools \
        python3-setuptools \
        python3-dev \
        python-is-python3 \
        device-tree-compiler \
        wget \
        zip \
        unzip \
        bc \
        bison \
        cpio \
        flex \
        kmod \
        libelf-dev \
        libssl-dev \
        libgnutls28-dev \
        libncurses-dev \
        uuid-dev \
        lz4 \
        zstd \
        e2fsprogs \
        dosfstools \
        parted \
        fdisk \
        kpartx \
        qemu-user-static \
        lib32stdc++6 \
        lib32z1 \
        swig \
        xxd \
        dos2unix \
        gdisk \
        file \
        patch \
        cmake \
        meson \
        ninja-build \
        pkg-config \
        ccache \
        gdb-multiarch \
        libc6-dev:arm64 \
        libc6-dev:armhf \
    && mkdir -p /etc/meson \
    && rm -rf /var/lib/apt/lists/*

# GUI App（LVGL + libdrm/GBM/EGL/GLESv2 + FreeType）交叉编译所需 arm64 dev 库。
# 单独成层：不动上面的工具链大层，保留其缓存、省磁盘与重建时间。
# Ubuntu 交叉走 multiarch sysroot 模型——headers 落 /usr/include，libs 落
# /usr/lib/aarch64-linux-gnu，aarch64-linux-gnu-gcc 配合 :arm64 dev 包即可定位。
RUN apt-get update && apt-get install -y --no-install-recommends \
        libdrm-dev:arm64 \
        libgbm-dev:arm64 \
        libegl-dev:arm64 \
        libgles-dev:arm64 \
        libfreetype-dev:arm64 \
    && rm -rf /var/lib/apt/lists/*

# Qualcomm QCS6490 平台 boot 组装所需：GRUB EFI 工具链（arm64 目标）+ FAT 工具。
# 单独成层保留上面缓存。grub-efi-arm64-bin 提供 /usr/lib/grub/arm64-efi/ 模块，
# grub-common 提供 grub-mkimage 二进制；mtools 提供 mcopy/mmd 免特权写 FAT 镜像。
RUN apt-get update && apt-get install -y --no-install-recommends \
        grub-efi-arm64-bin \
        grub-common \
        mtools \
    && rm -rf /var/lib/apt/lists/*

# RK3576 老 rockchip u-boot（2017.09 vendor 基，radxa next-dev-v2026.01）必须用 gcc-10 编：
# Ubuntu 24.04 自带 gcc-13，编出的二进制整体布局会让 RK3576 UFS DMA 读 buffer 落到坏物理地址
# → proper 读 UFS GPT 拿堆残渣崩（上板逐次实测坐实；radxa bsp 即用 Debian gcc-10，实测能引导
# UFS）。Ubuntu 24.04 仓库无 gcc-10，装独立可重定位的 kernel.org crosstool gcc-10.5 aarch64
# （prefix aarch64-linux-）。全平台 u-boot/kernel 默认工具链 = builder/base.py 的
# ComponentBuilder.CROSS = /opt/aarch64-gcc10/bin/aarch64-linux-（各 platform builder 不覆盖；
# app 构建仍用系统 gcc）。单独成层保留上面 apt 大层缓存。详见 openspec selfbuild-rk3576-spi-image。
RUN curl -fsSL "https://mirrors.edge.kernel.org/pub/tools/crosstool/files/bin/x86_64/10.5.0/x86_64-gcc-10.5.0-nolibc-aarch64-linux.tar.xz" \
        | tar -xJ -C /opt \
    && ln -sfn /opt/gcc-10.5.0-nolibc/aarch64-linux /opt/aarch64-gcc10 \
    && /opt/aarch64-gcc10/bin/aarch64-linux-gcc --version | head -1

# AMP 协处理器裸机固件（Cortex-A55 AArch32 HAL / RT-Thread）须用 newlib 版
# arm-none-eabi 工具链（提供 --specs=nosys.specs；glibc 向的 arm-linux-gnueabihf
# / aarch64-linux-gnu 编不出裸核）。钉官方 gcc-arm-none-eabi-10-2020-q4-major
# （gcc-10）：与 SDK Makefile/rtconfig 默认版本一致、与 flange u-boot/kernel 的
# gcc-10 约定一致，规避 gcc-13 在 Rockchip 低层代码上的隐蔽 miscompile。SDK
# Makefile 优先探测 prebuilts 路径、否则回退 PATH 上的 arm-none-eabi-；故软链
# 进 /usr/local/bin。rt-thread rtconfig 走 RTT_EXEC_PATH=/opt/arm-none-eabi-gcc10/bin
# 覆盖（见 builder/platforms/rockchip/amp.py）。单独成层保留上面 apt 大层缓存。
RUN curl -fsSL "https://developer.arm.com/-/media/Files/downloads/gnu-rm/10-2020q4/gcc-arm-none-eabi-10-2020-q4-major-x86_64-linux.tar.bz2" \
        | tar -xj -C /opt \
    && ln -sfn /opt/gcc-arm-none-eabi-10-2020-q4-major /opt/arm-none-eabi-gcc10 \
    && for t in /opt/arm-none-eabi-gcc10/bin/arm-none-eabi-*; do ln -sf "$t" /usr/local/bin/; done \
    && arm-none-eabi-gcc --version | head -1

# meson cross-file：路径与 builder/app.py 中 _BUILD_SYSTEMS["meson"] 模板引用
# 的 --cross-file /etc/meson/cross-<arch>.ini 一致。源文件可见于 docker/meson/。
COPY docker/meson/cross-aarch64.ini /etc/meson/cross-aarch64.ini
COPY docker/meson/cross-armhf.ini   /etc/meson/cross-armhf.ini

ENV PYTHONPATH=/workspace

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

WORKDIR /workspace
ENTRYPOINT ["entrypoint.sh"]
