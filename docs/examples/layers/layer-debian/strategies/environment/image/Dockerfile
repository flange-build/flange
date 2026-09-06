# Debian 13 完整构建环境；低层 gcc10 与用户态 Debian SDK 分离。
FROM flange-build:latest AS baseline
FROM --platform=linux/amd64 debian:trixie-slim
ENV DEBIAN_FRONTEND=noninteractive
RUN dpkg --add-architecture arm64 && apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl wget git python3 python3-venv python3-dev python3-pip python3-yaml \
    build-essential gcc-aarch64-linux-gnu g++-aarch64-linux-gnu binutils-aarch64-linux-gnu \
    cmake meson ninja-build pkg-config qemu-user-static debootstrap \
    e2fsprogs kmod file patch xz-utils zstd cpio device-tree-compiler \
    && python3 -m venv /opt/flange-python \
    && /opt/flange-python/bin/pip install jsonnet==0.22.0 pyyaml
COPY --from=baseline /opt/gcc-10.5.0-nolibc /opt/gcc-10.5.0-nolibc
RUN ln -s /opt/gcc-10.5.0-nolibc/aarch64-linux /opt/aarch64-gcc10 \
    && /opt/aarch64-gcc10/bin/aarch64-linux-gcc --version
# SDK 独立于最终 rootfs；包版本与归档摘要随环境保存，镜像摘要进入任务指纹。
RUN mkdir -p /tmp/sdk-debs /opt/flange-sdk /opt/flange-sdk-metadata \
    && cd /tmp/sdk-debs \
    && apt-get download libc6:arm64 libc6-dev:arm64 linux-libc-dev zlib1g:arm64 zlib1g-dev:arm64 libgcc-s1:arm64 libstdc++6:arm64 \
    && sha256sum *.deb > /opt/flange-sdk-metadata/sha256.txt \
    && for archive in *.deb; do dpkg-deb -x "$archive" /opt/flange-sdk; dpkg-deb -f "$archive" Package Version Architecture; done > /opt/flange-sdk-metadata/packages.txt \
    && rm -rf /tmp/sdk-debs
ENV PATH=/opt/flange-python/bin:$PATH
