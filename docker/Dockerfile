FROM --platform=linux/amd64 ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# 基础构建工具 + aarch64 交叉编译工具链 + 内核/U-Boot 构建依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc-aarch64-linux-gnu \
        g++-aarch64-linux-gnu \
        binutils-aarch64-linux-gnu \
        ca-certificates \
        curl \
        git \
        openssh-client \
        python3 \
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
        lz4 \
        zstd \
        e2fsprogs \
        dosfstools \
        parted \
        fdisk \
        kpartx \
        qemu-user-static \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONPATH=/workspace

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

WORKDIR /workspace
ENTRYPOINT ["entrypoint.sh"]
