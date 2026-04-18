FROM --platform=linux/amd64 ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# 基础构建工具 + aarch64 交叉编译工具链 + 内核/U-Boot 构建依赖
# + Allwinner U-Boot 构建依赖（32-bit ARM 工具链 + lib32 支持 Allwinner 专有工具）
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc-aarch64-linux-gnu \
        g++-aarch64-linux-gnu \
        binutils-aarch64-linux-gnu \
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
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONPATH=/workspace

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

WORKDIR /workspace
ENTRYPOINT ["entrypoint.sh"]
