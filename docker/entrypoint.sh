#!/bin/bash
set -e

# 从只读挂载位置复制 SSH 配置并修正权限
if [ -d /tmp/.ssh-host ]; then
    # 静默配置 SSH 密钥
    mkdir -p /root/.ssh
    # 用 `/.` 复制目录内容：目录为空时（如 CI 环境）glob `*` 会匹配失败，
    # 在 set -e 下导致 cp 报错中止；`/.` 形式即便空目录也正常返回
    cp -r /tmp/.ssh-host/. /root/.ssh/
    chmod 700 /root/.ssh
    chmod 600 /root/.ssh/* 2>/dev/null || true
    [ -f /root/.ssh/config ] && chmod 644 /root/.ssh/config
    [ -f /root/.ssh/known_hosts ] && chmod 644 /root/.ssh/known_hosts
fi

exec "$@"
