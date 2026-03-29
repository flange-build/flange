FROM --platform=linux/amd64 ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# 基础构建工具 + aarch64 交叉编译工具链 + 内核构建依赖
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
    && rm -rf /var/lib/apt/lists/*

# 安装 bazelisk（自动管理 Bazel 版本）
RUN curl -fsSL https://github.com/bazelbuild/bazelisk/releases/latest/download/bazelisk-linux-amd64 \
        -o /usr/local/bin/bazel \
    && chmod +x /usr/local/bin/bazel

WORKDIR /workspace
