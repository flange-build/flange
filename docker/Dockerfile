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

# meson cross-file：路径与 builder/app.py 中 _BUILD_SYSTEMS["meson"] 模板引用
# 的 --cross-file /etc/meson/cross-<arch>.ini 一致。源文件可见于 docker/meson/。
COPY docker/meson/cross-aarch64.ini /etc/meson/cross-aarch64.ini
COPY docker/meson/cross-armhf.ini   /etc/meson/cross-armhf.ini

ENV PYTHONPATH=/workspace

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

WORKDIR /workspace
ENTRYPOINT ["entrypoint.sh"]
