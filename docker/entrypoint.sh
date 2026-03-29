#!/bin/bash
set -e

# 从只读挂载位置复制 SSH 配置并修正权限
if [ -d /tmp/.ssh-host ]; then
    echo "[entrypoint] 配置 SSH 密钥..."
    mkdir -p /root/.ssh
    cp -r /tmp/.ssh-host/* /root/.ssh/
    chmod 700 /root/.ssh
    chmod 600 /root/.ssh/* 2>/dev/null || true
    [ -f /root/.ssh/config ] && chmod 644 /root/.ssh/config
    [ -f /root/.ssh/known_hosts ] && chmod 644 /root/.ssh/known_hosts
fi

echo "[entrypoint] 执行: $*"
exec "$@"
