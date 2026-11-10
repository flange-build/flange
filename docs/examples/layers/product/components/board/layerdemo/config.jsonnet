// 产品层组合 Debian 与共享应用；外部归档描述由准备脚本生成。
local base = import './base.libsonnet';
{ products+: ['minimal'], distro: 'debian', packages: ['layer-suite'], rootfs+: base }
