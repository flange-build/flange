# Bazel-to-Python 构建系统迁移实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 flange 构建系统从 Bazel+Starlark+Shell 三层架构迁移为 Python 统一架构，同时补齐 product/variant 配置维度、分区表系统、flash.sh 自动生成。

**Architecture:** Python 配置引擎（config/）处理三层继承+条件标记+追加语义，输出 FINAL_CONFIG dict。Python 构建引擎（builder/）基于基类/子类模式分离框架与平台策略，通过 subprocess 在 Docker 容器内直接调用系统命令（make/dd/parted 等），消除 shell 脚本中间层。增量构建通过内容哈希实现。

**Tech Stack:** Python 3.12+, pytest, subprocess, pathlib, dataclasses, configparser, docker compose

**Design Document:** `docs/python-build-system-design.html`（已由用户确认）

---

## File Structure

### New files to create

```
pyproject.toml                                  # Python 项目配置 + pytest 设置

config/                                         # 配置引擎
  __init__.py
  merge.py                                      # deep_merge + resolve_conditions
  registry.py                                   # 统一注册表 + get_board_config + resolve_config
  query.py                                      # get_valid_targets(), target 解析

platform/                                       # 平台配置 (.bzl → .py)
  rockchip/
    __init__.py
    config.py                                   # ROCKCHIP_PLATFORM dict
    rk3566/
      __init__.py
      config.py                                 # RK3566_SOC dict

board/                                          # 板级配置 (.bzl → .py, 扩展 products/variants)
  radxa-zero3w/
    config.py                                   # BOARD dict (替代 board.bzl)
  neons-core3566-nanob/
    config.py
  tspi-rk3566/
    config.py
  orangepi-cm4/
    config.py

builder/                                        # 构建引擎 + 平台策略
  __init__.py
  engine.py                                     # BuildEngine (依赖图 + 调度)
  docker.py                                     # DockerRunner (容器执行)
  source.py                                     # SourceManager (源码仓库管理)
  cache.py                                      # BuildCache (增量哈希)
  base.py                                       # ComponentBuilder 基类
  chroot.py                                     # ChrootContext (mount/umount 管理)
  collect.py                                    # 产物收集
  flash.py                                      # flash.sh 生成
  partition/
    __init__.py                                 # PartitionTable + Partition dataclass
    rockchip.py                                 # → parameter.txt 转换
    generic.py                                  # → sgdisk 命令
  platforms/
    __init__.py
    rockchip/
      __init__.py                               # create_builder() 工厂函数
      kernel.py                                 # RockchipKernelBuilder
      bootloader.py                             # RockchipBootloaderBuilder
      rootfs.py                                 # RockchipRootfsBuilder
      image.py                                  # RockchipImageBuilder

tests/                                          # 测试
  __init__.py
  config/
    __init__.py
    test_merge.py                               # deep_merge + resolve_conditions 测试
    test_registry.py                            # 注册表 + 配置合并测试
    test_query.py                               # target 解析测试
  builder/
    __init__.py
    test_cache.py                               # BuildCache 测试
    test_partition.py                           # 分区表转换测试
    test_flash.py                               # flash.sh 生成测试
```

### Files to modify

```
docker/Dockerfile                               # 删 bazelisk, 加 PYTHONPATH
docker-compose.yml                              # 删 bazel volume, 加 sources volume
envsetup.sh                                     # 重写: 支持 product/variant/lunch 持久化
.gitignore                                      # 加 sources/, __pycache__/, .pytest_cache/
```

### Files to delete (after migration verified)

```
MODULE.bazel, MODULE.bazel.lock, .bazelrc, .bazelversion
BUILD.bazel (root)
build/*.bzl, build/BUILD.bazel                  # 全部 14 个 .bzl + 1 BUILD
kernel/BUILD.bazel, kernel/rockchip/BUILD.bazel, kernel/rockchip/build.sh
bootloader/BUILD.bazel, bootloader/rockchip/BUILD.bazel, bootloader/rockchip/build.sh
rootfs/BUILD.bazel, rootfs/rockchip/BUILD.bazel, rootfs/rockchip/build_base.sh, rootfs/rockchip/build_customize.sh
image/BUILD.bazel, image/rockchip/BUILD.bazel, image/rockchip/build_boot.sh, image/rockchip/build_image.sh
image/rockchip/parameter.txt
board/*/board.bzl, board/*/BUILD.bazel          # 8 个文件
platform/rockchip/BUILD.bazel, platform/rockchip/config.bzl
platform/rockchip/rk3566/config.bzl, platform/rockchip/rk3566/BUILD.bazel
toolchain/ (entire directory)
packages/BUILD.bazel
app/adbd/BUILD.bazel
```

---

## Task 1: Python 项目脚手架

**Files:**
- Create: `pyproject.toml`
- Create: `config/__init__.py`
- Create: `builder/__init__.py`
- Create: `tests/__init__.py`, `tests/config/__init__.py`, `tests/builder/__init__.py`
- Modify: `.gitignore`

- [ ] **Step 1: 创建 pyproject.toml**

```toml
[project]
name = "flange"
version = "2.0.0"
description = "嵌入式 Linux 系统构建框架"
requires-python = ">=3.12"

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_functions = ["test_*"]
addopts = "-v --tb=short"
```

- [ ] **Step 2: 创建 __init__.py 占位文件**

创建以下空文件：
```
config/__init__.py
builder/__init__.py
builder/platforms/__init__.py
builder/platforms/rockchip/__init__.py
builder/partition/__init__.py
tests/__init__.py
tests/config/__init__.py
tests/builder/__init__.py
```

- [ ] **Step 3: 更新 .gitignore**

在现有 `.gitignore` 末尾追加：

```gitignore
# Python
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/

# 源码仓库
sources/
```

- [ ] **Step 4: 验证 pytest 可运行**

Run: `cd /Users/eki/Project/Embedded_Project/flange && python3 -m pytest --collect-only`
Expected: `no tests ran` (0 collected, no errors)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore config/__init__.py builder/__init__.py builder/platforms/__init__.py builder/platforms/rockchip/__init__.py builder/partition/__init__.py tests/__init__.py tests/config/__init__.py tests/builder/__init__.py
git commit -m "chore: Python 项目脚手架，pytest 基础设施"
```

---

## Task 2: 配置引擎 — deep_merge + resolve_conditions

**Files:**
- Create: `config/merge.py`
- Create: `tests/config/test_merge.py`

这是整个系统的基础。设计文档 §3.3 和 §3.4 的完整 Python 实现。纯函数，零外部依赖，完全可测试。

- [ ] **Step 1: 编写 deep_merge 测试**

```python
# tests/config/test_merge.py

from config.merge import deep_merge, resolve_conditions


class TestDeepMerge:
    def test_scalar_override(self):
        base = {"vendor": "rockchip", "arch": "aarch64"}
        override = {"arch": "armhf"}
        result = deep_merge(base, override)
        assert result == {"vendor": "rockchip", "arch": "armhf"}

    def test_dict_recursive_merge(self):
        base = {"kernel": {"repo": "a", "branch": "main"}}
        override = {"kernel": {"branch": "dev", "defconfig": "x"}}
        result = deep_merge(base, override)
        assert result == {"kernel": {"repo": "a", "branch": "dev", "defconfig": "x"}}

    def test_list_override(self):
        base = {"packages": ["systemd"]}
        override = {"packages": ["busybox"]}
        result = deep_merge(base, override)
        assert result == {"packages": ["busybox"]}

    def test_append_to_existing_list(self):
        base = {"packages": ["systemd"]}
        override = {"+packages": ["gdb"]}
        result = deep_merge(base, override)
        assert result == {"packages": ["systemd", "gdb"]}

    def test_append_preserves_prefix_when_no_base(self):
        base = {"vendor": "rockchip"}
        override = {"+packages:debug": ["gdb"]}
        result = deep_merge(base, override)
        assert result == {"vendor": "rockchip", "+packages:debug": ["gdb"]}

    def test_append_with_condition_to_existing(self):
        base = {"+packages:debug": ["strace"]}
        override = {"+packages:debug": ["gdb"]}
        result = deep_merge(base, override)
        assert result == {"+packages:debug": ["strace", "gdb"]}

    def test_base_keys_preserved(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = deep_merge(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_three_layer_merge(self):
        platform = {"vendor": "rockchip", "packages": ["systemd"]}
        soc = {"+packages": ["firmware"]}
        board = {"+packages": ["custom-driver"]}
        result = deep_merge(deep_merge(platform, soc), board)
        assert result == {
            "vendor": "rockchip",
            "packages": ["systemd", "firmware", "custom-driver"],
        }

    def test_nested_append(self):
        base = {"rootfs": {"packages": ["systemd"]}}
        override = {"rootfs": {"+packages": ["gdb"]}}
        result = deep_merge(base, override)
        assert result == {"rootfs": {"packages": ["systemd", "gdb"]}}

    def test_does_not_mutate_inputs(self):
        base = {"packages": ["a"]}
        override = {"+packages": ["b"]}
        deep_merge(base, override)
        assert base == {"packages": ["a"]}
        assert override == {"+packages": ["b"]}
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python3 -m pytest tests/config/test_merge.py::TestDeepMerge -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'config.merge'`

- [ ] **Step 3: 实现 deep_merge**

```python
# config/merge.py
"""配置合并引擎 — deep_merge 和 resolve_conditions。

设计文档 §3.3/§3.4 的完整实现。
"""

from copy import deepcopy


def deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个配置 dict，支持 +key 追加语义。

    规则：
    - 标量: override 覆盖 base
    - dict: 递归合并
    - list: override 完全替换 base
    - +key (list): 追加到 base 中同名 key (去掉 + 前缀)
    - +key 且 base 中无对应 key: 保留 +key 原样传递给下游

    不修改输入参数，返回新 dict。
    """
    result = deepcopy(base)

    for key, value in override.items():
        if key.startswith("+"):
            base_key = key[1:]
            if base_key in result and isinstance(result[base_key], list):
                result[base_key] = result[base_key] + deepcopy(value)
            elif key in result and isinstance(result[key], list):
                result[key] = result[key] + deepcopy(value)
            else:
                result[key] = deepcopy(value)
        elif key in result and isinstance(value, dict) and isinstance(result[key], dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)

    return result
```

- [ ] **Step 4: 运行 deep_merge 测试**

Run: `python3 -m pytest tests/config/test_merge.py::TestDeepMerge -v`
Expected: ALL PASS

- [ ] **Step 5: 编写 resolve_conditions 测试**

在 `tests/config/test_merge.py` 末尾追加：

```python
class TestResolveConditions:
    def test_unconditional_keys_preserved(self):
        config = {"vendor": "rockchip", "packages": ["systemd"]}
        result = resolve_conditions(config, product="default", variant="release")
        assert result == {"vendor": "rockchip", "packages": ["systemd"]}

    def test_matching_variant_override(self):
        config = {"packages": ["base"], "packages:debug": ["gdb"]}
        result = resolve_conditions(config, product="default", variant="debug")
        assert result["packages"] == ["gdb"]

    def test_non_matching_variant_discarded(self):
        config = {"packages": ["base"], "packages:debug": ["gdb"]}
        result = resolve_conditions(config, product="default", variant="release")
        assert result == {"packages": ["base"]}

    def test_matching_variant_append(self):
        config = {"packages": ["base"], "+packages:debug": ["gdb", "strace"]}
        result = resolve_conditions(config, product="default", variant="debug")
        assert result["packages"] == ["base", "gdb", "strace"]

    def test_matching_product_append(self):
        config = {"packages": ["base"], "+packages:smart-display": ["weston"]}
        result = resolve_conditions(config, product="smart-display", variant="release")
        assert result["packages"] == ["base", "weston"]

    def test_non_matching_product_discarded(self):
        config = {"packages": ["base"], "+packages:gateway": ["mosquitto"]}
        result = resolve_conditions(config, product="smart-display", variant="release")
        assert result == {"packages": ["base"]}

    def test_multiple_conditions_apply(self):
        config = {
            "packages": ["base"],
            "+packages:debug": ["gdb"],
            "+packages:smart-display": ["weston"],
            "+packages:gateway": ["mosquitto"],
        }
        result = resolve_conditions(config, product="smart-display", variant="debug")
        assert "base" in result["packages"]
        assert "gdb" in result["packages"]
        assert "weston" in result["packages"]
        assert "mosquitto" not in result["packages"]

    def test_nested_dict_conditions(self):
        config = {
            "rootfs": {
                "packages": ["systemd"],
                "+packages:debug": ["gdb"],
            }
        }
        result = resolve_conditions(config, product="default", variant="debug")
        assert result["rootfs"]["packages"] == ["systemd", "gdb"]

    def test_conditional_override_replaces(self):
        config = {
            "partitions": {"size": "4G"},
            "partitions:smart-display": {"size": "8G", "data": True},
        }
        result = resolve_conditions(config, product="smart-display", variant="release")
        assert result["partitions"] == {"size": "8G", "data": True}

    def test_unconditional_append_no_condition(self):
        config = {"packages": ["base"], "+packages": ["extra"]}
        result = resolve_conditions(config, product="default", variant="release")
        assert result["packages"] == ["base", "extra"]

    def test_full_three_layer_scenario(self):
        """模拟完整的 platform → SoC → board 合并后的 resolve"""
        merged = {
            "vendor": "rockchip",
            "flash_tool": "upgrade_tool",
            "rootfs": {
                "packages": ["systemd", "network-manager"],
                "+packages": ["firmware-rk3566", "custom-driver"],
                "+packages:debug": ["gdb", "strace", "tcpdump"],
                "+packages:smart-display": ["weston", "chromium"],
                "+packages:gateway": ["mosquitto"],
            },
            "partitions": {
                "format": "gpt",
                "entries": [{"name": "rootfs", "size": "4G"}],
            },
            "partitions:smart-display": {
                "format": "gpt",
                "entries": [{"name": "rootfs", "size": "8G"}, {"name": "data", "size": "remaining"}],
            },
        }
        result = resolve_conditions(merged, product="smart-display", variant="debug")
        pkgs = result["rootfs"]["packages"]
        assert "systemd" in pkgs
        assert "firmware-rk3566" in pkgs
        assert "gdb" in pkgs
        assert "weston" in pkgs
        assert "mosquitto" not in pkgs
        assert result["partitions"]["entries"][0]["size"] == "8G"
```

- [ ] **Step 6: 运行测试，确认失败**

Run: `python3 -m pytest tests/config/test_merge.py::TestResolveConditions -v`
Expected: FAIL — `resolve_conditions` not yet implemented

- [ ] **Step 7: 实现 resolve_conditions**

在 `config/merge.py` 末尾追加：

```python
def resolve_conditions(config: dict, product: str, variant: str) -> dict:
    """解析条件标记，返回扁平的 FINAL_CONFIG。

    设计文档 §3.5 Step 2 的实现。

    处理顺序：
    1. 收集所有无条件 key
    2. 处理无条件 +key（追加到对应 base key）
    3. 处理匹配条件的 key:cond（覆盖）和 +key:cond（追加）
    4. 丢弃不匹配条件的 key
    5. 递归处理嵌套 dict
    """
    active = {product, variant}
    result = {}

    # Pass 1: 无条件 key (不带 + 和 :)
    for key, value in config.items():
        if not key.startswith("+") and ":" not in key:
            if isinstance(value, dict):
                result[key] = resolve_conditions(value, product, variant)
            else:
                result[key] = deepcopy(value)

    # Pass 2: 无条件追加 +key (不带 :)
    for key, value in config.items():
        if key.startswith("+") and ":" not in key:
            base_key = key[1:]
            if base_key in result and isinstance(result[base_key], list):
                result[base_key] = result[base_key] + deepcopy(value)
            else:
                result[base_key] = deepcopy(value)

    # Pass 3: 条件 key:cond (覆盖) 和 +key:cond (追加)
    for key, value in config.items():
        if ":" not in key:
            continue
        if key.startswith("+"):
            raw = key[1:]
            base_key, cond = raw.rsplit(":", 1)
            if cond in active:
                if base_key in result and isinstance(result[base_key], list):
                    result[base_key] = result[base_key] + deepcopy(value)
                else:
                    result[base_key] = deepcopy(value)
        else:
            base_key, cond = key.rsplit(":", 1)
            if cond in active:
                if isinstance(value, dict):
                    result[base_key] = resolve_conditions(value, product, variant)
                else:
                    result[base_key] = deepcopy(value)

    return result
```

- [ ] **Step 8: 运行全部测试**

Run: `python3 -m pytest tests/config/test_merge.py -v`
Expected: ALL PASS (21 tests)

- [ ] **Step 9: Commit**

```bash
git add config/merge.py tests/config/test_merge.py
git commit -m "feat(config): 实现 deep_merge 和 resolve_conditions，支持 +追加和条件标记"
```

---

## Task 3: 配置引擎 — 注册表 + 板级配置迁移

**Files:**
- Create: `config/registry.py`
- Create: `config/query.py`
- Create: `platform/rockchip/__init__.py`, `platform/rockchip/config.py`
- Create: `platform/rockchip/rk3566/__init__.py`, `platform/rockchip/rk3566/config.py`
- Create: `board/radxa-zero3w/config.py` (以及其他 3 块板子)
- Create: `tests/config/test_registry.py`
- Create: `tests/config/test_query.py`

- [ ] **Step 1: 迁移平台配置 .bzl → .py**

```python
# platform/rockchip/__init__.py
# (空文件)
```

```python
# platform/rockchip/config.py
"""Rockchip 平台配置 — 第一层继承"""

ROCKCHIP_PLATFORM = {
    "vendor": "rockchip",
    "flash_tool": "upgrade_tool",
    "arch": "aarch64",
    "rkbin": {
        "repo": "https://github.com/radxa/rkbin",
        "branch": "develop-v2024.10",
    },
    "rootfs": {
        "packages": [
            "systemd",
            "systemd-sysv",
            "dbus",
            "network-manager",
            "iputils-ping",
            "iproute2",
            "openssh-server",
            "sudo",
            "bash",
            "ca-certificates",
            "locales",
        ],
    },
    "+rootfs": {
        "+packages:debug": ["gdb", "strace", "tcpdump", "valgrind"],
    },
}
```

```python
# platform/rockchip/rk3566/__init__.py
# (空文件)
```

```python
# platform/rockchip/rk3566/config.py
"""RK3566 SoC 配置 — 第二层继承"""

RK3566_SOC = {
    "platform": "rockchip",
    "soc": "rk3566",
    "arch": "aarch64",
    "rkbin": {
        "ini_prefix": "RK3566",
        "trust_ini_prefix": "RK3568",
    },
    "bootloader": {
        "defconfig": "rk3568_defconfig",
    },
    "kernel": {
        "defconfig": "rockchip_linux_defconfig",
        "dts_dir": "rockchip",
    },
    "partitions": {
        "format": "gpt",
        "sector_size": 512,
        "entries": [
            {"name": "idbloader", "offset": "0x40", "size": "0x2000", "type": "raw"},
            {"name": "uboot", "offset": "0x4000", "size": "0x2000", "type": "raw"},
            {"name": "boot", "offset": "0x8000", "size": "0x20000", "type": "ext4"},
            {"name": "rootfs", "offset": "0x40000", "size": "0x200000", "type": "ext4"},
            {"name": "userdata", "offset": "0x240000", "size": "remaining", "type": "ext4"},
        ],
    },
}
```

- [ ] **Step 2: 迁移板级配置 (4 块板子)**

```python
# board/radxa-zero3w/config.py
"""Radxa Zero 3W (RK3566) 板级配置"""

BOARD = {
    "board": "radxa-zero3w",
    "soc": "rk3566",
    "platform": "rockchip",
    "products": ["default"],
    "variants": ["debug", "release"],
    "kernel": {
        "repo": "ssh://git@gitlab-r.eric3u.xyz:20022/argon/kernel.git",
        "branch": "linux-6.1-stan-rkr4.1-buildroot",
        "commit": "",
        "dts": "rk3566-radxa-zero-3w",
    },
    "bootloader": {
        "repo": "https://github.com/radxa/u-boot",
        "branch": "next-dev-v2026.01",
        "commit": "",
    },
    "boot": {
        "dtb_overlays": [],
        "default_overlays": [],
        "kernel_args": "console=ttyS2,1500000 loglevel=7",
    },
    "rootfs": {
        "url": "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.4-base-arm64.tar.gz",
        "custom_packages": ["adbd"],
    },
}
```

```python
# board/neons-core3566-nanob/config.py
"""Neons Core3566 Nano B (RK3566) 板级配置"""

BOARD = {
    "board": "neons-core3566-nanob",
    "soc": "rk3566",
    "platform": "rockchip",
    "products": ["default"],
    "variants": ["debug", "release"],
    "kernel": {
        "repo": "ssh://git@gitlab-r.eric3u.xyz:20022/argon/kernel.git",
        "branch": "linux-6.1-stan-rkr4.1-buildroot",
        "commit": "e62b45adc7f89f5c8ea1918960b8c78e7c97ebf5",
        "dts": "rk3566-neons-core-wavesharecm4-nano-b",
    },
    "bootloader": {
        "repo": "https://github.com/radxa/u-boot",
        "branch": "next-dev-v2026.01",
        "commit": "3c60a711e61015c1a61247837afbeaa85bd7fbf2",
    },
    "boot": {
        "dtb_overlays": [],
        "default_overlays": [],
        "kernel_args": "console=ttyS2,1500000 loglevel=7",
    },
    "rootfs": {
        "url": "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.4-base-arm64.tar.gz",
        "custom_packages": ["adbd"],
    },
}
```

```python
# board/tspi-rk3566/config.py
"""TSpi RK3566 板级配置"""

BOARD = {
    "board": "tspi-rk3566",
    "soc": "rk3566",
    "platform": "rockchip",
    "products": ["default"],
    "variants": ["debug", "release"],
    "kernel": {
        "repo": "ssh://git@gitlab-r.eric3u.xyz:20022/argon/kernel.git",
        "branch": "linux-6.1-stan-rkr4.1-buildroot",
        "commit": "d425e02d22a75945fc79a10e736c1de76ca615c8",
        "dts": "tspi-rk3566-user-v10-ext39-linux",
    },
    "bootloader": {
        "repo": "https://github.com/radxa/u-boot",
        "branch": "next-dev-v2026.01",
        "commit": "3c60a711e61015c1a61247837afbeaa85bd7fbf2",
    },
    "boot": {
        "dtb_overlays": [],
        "default_overlays": [],
        "kernel_args": "console=ttyS2,1500000 loglevel=7",
    },
    "rootfs": {
        "url": "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.4-base-arm64.tar.gz",
        "custom_packages": ["adbd"],
    },
}
```

```python
# board/orangepi-cm4/config.py
"""Orange Pi CM4 (RK3566) 板级配置"""

BOARD = {
    "board": "orangepi-cm4",
    "soc": "rk3566",
    "platform": "rockchip",
    "products": ["default"],
    "variants": ["debug", "release"],
    "kernel": {
        "repo": "ssh://git@gitlab-r.eric3u.xyz:20022/argon/kernel.git",
        "branch": "linux-6.1-stan-rkr4.1-buildroot",
        "commit": "",
        "dts": "rk3566-orangepi-cm4-base",
    },
    "bootloader": {
        "repo": "https://github.com/radxa/u-boot",
        "branch": "next-dev-v2026.01",
        "commit": "",
    },
    "boot": {
        "dtb_overlays": [],
        "default_overlays": [],
        "kernel_args": "console=ttyS2,1500000 loglevel=7",
    },
    "rootfs": {
        "url": "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.4-base-arm64.tar.gz",
        "custom_packages": ["adbd"],
    },
}
```

- [ ] **Step 3: 实现注册表**

```python
# config/registry.py
"""统一注册表 — 管理平台/SoC/板级配置的注册、合并与查询。

自动扫描 board/*/config.py 发现板子，通过 platform/soc 链加载继承配置。
"""

import importlib
from pathlib import Path
from config.merge import deep_merge, resolve_conditions

# 平台/SoC 配置映射 — 新增平台时在这里注册
_PLATFORM_MODULES = {
    "rockchip": "platform.rockchip.config",
}

_SOC_MODULES = {
    "rk3566": "platform.rockchip.rk3566.config",
}


def _load_config(module_path: str, attr: str) -> dict:
    """从 Python 模块加载配置 dict"""
    mod = importlib.import_module(module_path)
    return getattr(mod, attr)


def discover_boards(project_root: Path = None) -> dict:
    """扫描 board/*/config.py 发现所有已注册的板子"""
    root = project_root or Path.cwd()
    boards = {}
    for config_file in sorted((root / "board").glob("*/config.py")):
        board_name = config_file.parent.name
        module_path = f"board.{board_name.replace('-', '_')}.config"
        try:
            mod = importlib.import_module(module_path)
            boards[board_name] = mod.BOARD
        except (ImportError, AttributeError):
            # board 目录存在但 config.py 格式不对，跳过
            pass
    return boards


def get_board_config(board_name: str, boards: dict = None) -> dict:
    """返回三层合并后的完整配置 (platform → SoC → board)。"""
    if boards is None:
        boards = discover_boards()
    if board_name not in boards:
        raise ValueError(f"板子 '{board_name}' 未注册，已注册: {list(boards.keys())}")

    board = boards[board_name]
    platform_name = board["platform"]
    soc_name = board["soc"]

    if platform_name not in _PLATFORM_MODULES:
        raise ValueError(f"平台 '{platform_name}' 未注册")
    if soc_name not in _SOC_MODULES:
        raise ValueError(f"SoC '{soc_name}' 未注册")

    platform_config = _load_config(_PLATFORM_MODULES[platform_name], "ROCKCHIP_PLATFORM")
    soc_config = _load_config(_SOC_MODULES[soc_name], "RK3566_SOC")

    return deep_merge(deep_merge(platform_config, soc_config), board)


def resolve_config(board_name: str, product: str = "default",
                   variant: str = "release", boards: dict = None) -> dict:
    """完整配置解析: 三层合并 → 条件标记解析 → FINAL_CONFIG。"""
    merged = get_board_config(board_name, boards)
    return resolve_conditions(merged, product, variant)
```

- [ ] **Step 4: 实现 query 模块**

```python
# config/query.py
"""配置查询工具 — 给 CLI lunch 使用。"""

from config.registry import discover_boards


def get_valid_targets(boards: dict = None) -> list:
    """返回所有合法的 target 字符串列表。

    格式: <board>-<product>-<variant>
    """
    if boards is None:
        boards = discover_boards()

    targets = []
    for board_name, board_config in sorted(boards.items()):
        products = board_config.get("products", ["default"])
        variants = board_config.get("variants", ["release"])
        for product in products:
            for variant in variants:
                targets.append(f"{board_name}-{product}-{variant}")
    return targets


def parse_target(target: str, boards: dict = None) -> dict:
    """解析 target 字符串为 {board, product, variant} dict。

    支持:
    - "radxa-zero3w-smart-display-debug" → 完整指定
    - "radxa-zero3w" → 只指定 board，product/variant 使用默认值
    """
    if boards is None:
        boards = discover_boards()

    # 尝试完全匹配已注册的板子名
    if target in boards:
        board_config = boards[target]
        return {
            "board": target,
            "product": board_config.get("products", ["default"])[0],
            "variant": board_config.get("variants", ["release"])[0],
        }

    # 尝试从后向前拆分: board-product-variant
    for board_name in sorted(boards.keys(), key=len, reverse=True):
        if target.startswith(board_name + "-"):
            remainder = target[len(board_name) + 1:]
            parts = remainder.rsplit("-", 1)
            if len(parts) == 2:
                product, variant = parts
                return {"board": board_name, "product": product, "variant": variant}
            elif len(parts) == 1:
                return {"board": board_name, "product": parts[0], "variant": "release"}

    raise ValueError(f"无法解析 target: '{target}'")
```

- [ ] **Step 5: 编写注册表测试**

```python
# tests/config/test_registry.py

import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.registry import get_board_config, resolve_config


class TestGetBoardConfig:
    def test_radxa_zero3w_three_layer_merge(self):
        config = get_board_config("radxa-zero3w")
        # 来自 platform
        assert config["vendor"] == "rockchip"
        assert config["flash_tool"] == "upgrade_tool"
        # 来自 SoC
        assert config["soc"] == "rk3566"
        assert config["bootloader"]["defconfig"] == "rk3568_defconfig"
        # 来自 board
        assert config["board"] == "radxa-zero3w"
        assert "rk3566-radxa-zero-3w" in config["kernel"]["dts"]

    def test_packages_merged_from_platform(self):
        config = get_board_config("radxa-zero3w")
        pkgs = config["rootfs"]["packages"]
        assert "systemd" in pkgs

    def test_unknown_board_raises(self):
        import pytest
        with pytest.raises(ValueError, match="未注册"):
            get_board_config("nonexistent-board")


class TestResolveConfig:
    def test_debug_variant_adds_packages(self):
        config = resolve_config("radxa-zero3w", variant="debug")
        pkgs = config["rootfs"]["packages"]
        assert "systemd" in pkgs
        # debug 包来自 platform 的 +packages:debug
        assert "gdb" in pkgs

    def test_release_variant_no_debug_packages(self):
        config = resolve_config("radxa-zero3w", variant="release")
        pkgs = config["rootfs"]["packages"]
        assert "systemd" in pkgs
        assert "gdb" not in pkgs

    def test_partitions_from_soc(self):
        config = resolve_config("radxa-zero3w")
        assert config["partitions"]["format"] == "gpt"
        names = [e["name"] for e in config["partitions"]["entries"]]
        assert "idbloader" in names
        assert "rootfs" in names

    def test_all_boards_resolve_without_error(self):
        for board in ["radxa-zero3w", "neons-core3566-nanob", "tspi-rk3566", "orangepi-cm4"]:
            config = resolve_config(board)
            assert config["platform"] == "rockchip"
            assert config["arch"] == "aarch64"
```

- [ ] **Step 6: 编写 query 测试**

```python
# tests/config/test_query.py

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.query import get_valid_targets, parse_target


class TestGetValidTargets:
    def test_returns_list(self):
        targets = get_valid_targets()
        assert isinstance(targets, list)
        assert len(targets) > 0

    def test_format_board_product_variant(self):
        targets = get_valid_targets()
        for t in targets:
            parts = t.split("-")
            assert len(parts) >= 3  # 板子名本身可能含 -


class TestParseTarget:
    def test_board_only(self):
        result = parse_target("radxa-zero3w")
        assert result["board"] == "radxa-zero3w"
        assert result["product"] == "default"

    def test_full_target(self):
        result = parse_target("radxa-zero3w-default-debug")
        assert result["board"] == "radxa-zero3w"
        assert result["product"] == "default"
        assert result["variant"] == "debug"

    def test_board_with_hyphens(self):
        result = parse_target("neons-core3566-nanob")
        assert result["board"] == "neons-core3566-nanob"

    def test_invalid_target_raises(self):
        import pytest
        with pytest.raises(ValueError, match="无法解析"):
            parse_target("totally-fake-board-name-xyz")
```

- [ ] **Step 7: 运行全部配置测试**

Run: `python3 -m pytest tests/config/ -v`
Expected: ALL PASS

注意：需要确保 `board/*/config.py` 中使用下划线风格的模块名。由于 board 目录名含连字符（如 `radxa-zero3w`），Python import 需要特殊处理。在 `registry.py` 的 `discover_boards` 中已通过 `board_name.replace('-', '_')` 处理。但这意味着目录需要是合法 Python 包名，或者改用 `importlib.util.spec_from_file_location` 直接加载文件。

如果测试因 import 连字符目录失败，修改 `discover_boards`:

```python
def discover_boards(project_root: Path = None) -> dict:
    root = project_root or Path.cwd()
    boards = {}
    for config_file in sorted((root / "board").glob("*/config.py")):
        board_name = config_file.parent.name
        spec = importlib.util.spec_from_file_location(
            f"board_{board_name.replace('-', '_')}", config_file)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if hasattr(mod, "BOARD"):
            boards[board_name] = mod.BOARD
    return boards
```

同样，平台配置加载也需要用文件路径：

```python
def _load_platform_config(platform: str) -> dict:
    root = Path.cwd()
    config_file = root / "platform" / platform / "config.py"
    spec = importlib.util.spec_from_file_location(f"platform_{platform}", config_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.ROCKCHIP_PLATFORM  # TODO: 通用化属性名

def _load_soc_config(platform: str, soc: str) -> dict:
    root = Path.cwd()
    config_file = root / "platform" / platform / soc / "config.py"
    spec = importlib.util.spec_from_file_location(f"soc_{soc}", config_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # 按约定：SoC 配置变量名为大写 SOC 名 + _SOC
    for attr in dir(mod):
        val = getattr(mod, attr)
        if isinstance(val, dict) and val.get("soc") == soc:
            return val
    raise ValueError(f"SoC config '{soc}' 未找到配置 dict")
```

- [ ] **Step 8: 确认全部测试通过后 Commit**

```bash
git add config/registry.py config/query.py platform/ board/*/config.py tests/config/test_registry.py tests/config/test_query.py
git commit -m "feat(config): 统一注册表，迁移 4 块板子配置 .bzl→.py，支持 product/variant"
```

---

## Task 4: 构建引擎基础设施

**Files:**
- Create: `builder/docker.py`
- Create: `builder/source.py`
- Create: `builder/cache.py`
- Create: `builder/base.py`
- Create: `builder/chroot.py`
- Create: `builder/engine.py`
- Create: `tests/builder/test_cache.py`

- [ ] **Step 1: 实现 DockerRunner**

```python
# builder/docker.py
"""Docker 容器执行封装。"""

import subprocess
from pathlib import Path


class BuildError(Exception):
    """构建过程中的错误"""
    pass


class DockerRunner:
    """在 Docker 容器内执行命令。"""

    def __init__(self, project_dir: Path = None):
        self.project_dir = project_dir or Path.cwd()

    def run(self, cmd: list, *, cwd: str = None, env: dict = None,
            privileged: bool = False, check: bool = True,
            capture: bool = False) -> subprocess.CompletedProcess:
        docker_cmd = ["docker", "compose", "run", "--rm"]
        if privileged:
            docker_cmd.append("--privileged")
        if cwd:
            docker_cmd.extend(["-w", str(cwd)])
        if env:
            for k, v in env.items():
                docker_cmd.extend(["-e", f"{k}={v}"])
        docker_cmd.append("build")
        docker_cmd.extend([str(c) for c in cmd])

        kwargs = {"cwd": self.project_dir}
        if capture:
            kwargs["capture_output"] = True
            kwargs["text"] = True

        result = subprocess.run(docker_cmd, **kwargs)
        if check and result.returncode != 0:
            raise BuildError(f"Docker 命令失败 (exit {result.returncode}): {' '.join(str(c) for c in cmd)}")
        return result

    def run_privileged(self, cmd: list, **kwargs):
        return self.run(cmd, privileged=True, **kwargs)
```

- [ ] **Step 2: 实现 SourceManager**

```python
# builder/source.py
"""源码仓库管理 — 替代 Bazel module extensions。"""

import os
import subprocess
from pathlib import Path


class SourceManager:
    def __init__(self, sources_dir: Path = None):
        self.sources_dir = sources_dir or Path("sources")

    def ensure(self, component: str, config: dict) -> Path:
        """确保源码就绪，返回源码路径。"""
        comp_config = config.get(component, {})

        local_path = comp_config.get("local_path")
        if local_path:
            return Path(local_path)

        repo_dir = self.sources_dir / component / config["board"]

        if not repo_dir.exists():
            self._clone(
                repo=comp_config["repo"],
                branch=comp_config["branch"],
                dest=repo_dir,
                commit=comp_config.get("commit", ""),
            )
        elif comp_config.get("commit"):
            current = self._rev_parse(repo_dir)
            if current != comp_config["commit"]:
                self._fetch_checkout(repo_dir, comp_config["commit"])

        return repo_dir

    def ensure_firmware(self, platform: str, config: dict) -> Path:
        """确保平台固件仓库就绪（如 Rockchip rkbin）。"""
        rkbin_config = config.get("rkbin", {})
        if not rkbin_config.get("repo"):
            return Path("")

        fw_dir = self.sources_dir / "firmware" / platform
        if not fw_dir.exists():
            self._clone(
                repo=rkbin_config["repo"],
                branch=rkbin_config["branch"],
                dest=fw_dir,
            )
        return fw_dir

    def _clone(self, repo: str, branch: str, dest: Path, commit: str = ""):
        dest.parent.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "GIT_SSH_COMMAND": "ssh -o StrictHostKeyChecking=accept-new"}
        cmd = ["git", "clone", "--depth=1", "-b", branch, repo, str(dest)]
        subprocess.run(cmd, env=env, check=True, timeout=1800)
        if commit:
            subprocess.run(["git", "fetch", "--depth=1", "origin", commit],
                           cwd=dest, env=env, check=True, timeout=600)
            subprocess.run(["git", "checkout", commit], cwd=dest, check=True)

    def _rev_parse(self, repo_dir: Path) -> str:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_dir,
            capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def _fetch_checkout(self, repo_dir: Path, commit: str):
        env = {**os.environ, "GIT_SSH_COMMAND": "ssh -o StrictHostKeyChecking=accept-new"}
        subprocess.run(["git", "fetch", "--depth=1", "origin", commit],
                       cwd=repo_dir, env=env, check=True, timeout=600)
        subprocess.run(["git", "checkout", commit], cwd=repo_dir, check=True)
```

- [ ] **Step 3: 实现 BuildCache**

```python
# builder/cache.py
"""增量构建缓存 — 基于内容哈希。"""

import hashlib
import json
import subprocess
from pathlib import Path


class BuildCache:
    def __init__(self, config: dict):
        self.config = config
        board = config["board"]
        product = config.get("product", "default")
        variant = config.get("variant", "release")
        self.target_dir = Path("target") / board / product / variant

    def is_up_to_date(self, component: str) -> bool:
        hash_file = self.target_dir / component / ".build_hash"
        if not hash_file.exists():
            return False
        stored = hash_file.read_text().strip()
        return stored == self.compute_hash(component)

    def store(self, component: str):
        hash_file = self.target_dir / component / ".build_hash"
        hash_file.parent.mkdir(parents=True, exist_ok=True)
        hash_file.write_text(self.compute_hash(component))

    def compute_hash(self, component: str) -> str:
        h = hashlib.sha256()

        # 组件配置值
        comp_config = self.config.get(component, {})
        h.update(json.dumps(comp_config, sort_keys=True, default=str).encode())

        # 全局影响构建的配置
        for key in ["arch", "platform", "soc", "board"]:
            h.update(self.config.get(key, "").encode())

        # 源码 commit
        src_dir = Path("sources") / component / self.config["board"]
        if src_dir.exists():
            try:
                result = subprocess.run(
                    ["git", "rev-parse", "HEAD"], cwd=src_dir,
                    capture_output=True, text=True, check=True)
                h.update(result.stdout.strip().encode())
            except subprocess.CalledProcessError:
                h.update(b"unknown-commit")

        # 补丁文件内容
        platform = self.config.get("platform", "")
        board = self.config["board"]
        for patch_dir in [
            Path(f"platform/{platform}/patches/{component}"),
            Path(f"board/{board}/patches/{component}"),
        ]:
            if patch_dir.exists():
                for p in sorted(patch_dir.glob("*.patch")):
                    h.update(p.read_bytes())

        return h.hexdigest()[:16]
```

- [ ] **Step 4: 实现 ComponentBuilder 基类**

```python
# builder/base.py
"""组件构建基类 — 管理源码生命周期、补丁应用。"""

from abc import ABC, abstractmethod
from pathlib import Path

from builder.docker import DockerRunner
from builder.source import SourceManager


class ComponentBuilder(ABC):
    component: str = ""

    def __init__(self, docker: DockerRunner, source: SourceManager):
        self.docker = docker
        self.source = source

    def build(self, config: dict) -> dict:
        src_dir = self.source.ensure(self.component, config)

        if not config.get("_local_mode", {}).get(self.component):
            self.reset_source(src_dir)
            self.apply_patches(src_dir, config)

        self.configure(src_dir, config)
        self.compile(src_dir, config)
        return self.collect(src_dir, config)

    def reset_source(self, src_dir: Path):
        self.docker.run(["git", "checkout", "-f", "."], cwd=str(src_dir))

    def apply_patches(self, src_dir: Path, config: dict):
        platform = config["platform"]
        board = config["board"]
        platform_patches = sorted(
            Path(f"platform/{platform}/patches/{self.component}").glob("*.patch")
        ) if Path(f"platform/{platform}/patches/{self.component}").exists() else []
        board_patches = sorted(
            Path(f"board/{board}/patches/{self.component}").glob("*.patch")
        ) if Path(f"board/{board}/patches/{self.component}").exists() else []

        for patch in platform_patches + board_patches:
            try:
                self.docker.run(["git", "apply", str(patch)], cwd=str(src_dir))
            except Exception:
                self.docker.run(["patch", "-p1", "-i", str(patch)], cwd=str(src_dir))

    @abstractmethod
    def configure(self, src_dir: Path, config: dict):
        ...

    @abstractmethod
    def compile(self, src_dir: Path, config: dict):
        ...

    @abstractmethod
    def collect(self, src_dir: Path, config: dict) -> dict:
        ...

    def make(self, src_dir: Path, targets: list, *,
             arch: str = "", cross: str = "", jobs: int = 0, extra: list = None):
        cmd = ["make"]
        if arch:
            cmd.append(f"ARCH={arch}")
        if cross:
            cmd.append(f"CROSS_COMPILE={cross}")
        cmd.append(f"-j{jobs}" if jobs else "-j$(nproc)")
        cmd.extend(extra or [])
        cmd.extend(targets)
        self.docker.run(cmd, cwd=str(src_dir))
```

- [ ] **Step 5: 实现 ChrootContext**

```python
# builder/chroot.py
"""Chroot 上下文管理器 — 安全管理 mount/umount 生命周期。"""

from pathlib import Path
from builder.docker import DockerRunner


class ChrootContext:
    def __init__(self, rootfs_dir: Path, docker: DockerRunner):
        self.rootfs = rootfs_dir
        self.docker = docker
        self._mounts = []

    def __enter__(self):
        self._mount("proc", self.rootfs / "proc", fstype="proc")
        self._mount("sysfs", self.rootfs / "sys", fstype="sysfs")
        self._bind("/dev", self.rootfs / "dev")
        self._bind("/dev/pts", self.rootfs / "dev/pts")
        return self

    def __exit__(self, *exc):
        for mount_point in reversed(self._mounts):
            self.docker.run_privileged(
                ["umount", "-l", str(mount_point)], check=False)
        return False

    def run(self, cmd: list, **kwargs):
        self.docker.run_privileged(
            ["chroot", str(self.rootfs)] + cmd, **kwargs)

    def bind_mount(self, src: str, dest: Path = None):
        dest = dest or (self.rootfs / src.lstrip("/"))
        self._bind(src, dest)

    def _mount(self, src, dest, fstype=None):
        Path(dest).mkdir(parents=True, exist_ok=True)
        cmd = ["mount"]
        if fstype:
            cmd.extend(["-t", fstype])
        cmd.extend([src, str(dest)])
        self.docker.run_privileged(cmd)
        self._mounts.append(dest)

    def _bind(self, src, dest):
        Path(dest).mkdir(parents=True, exist_ok=True)
        self.docker.run_privileged(["mount", "-o", "bind", str(src), str(dest)])
        self._mounts.append(dest)
```

- [ ] **Step 6: 实现 BuildEngine**

```python
# builder/engine.py
"""构建引擎 — 管理依赖图、增量检查和调度。"""

import importlib
import logging
from pathlib import Path

from builder.docker import DockerRunner
from builder.source import SourceManager
from builder.cache import BuildCache

log = logging.getLogger("flange")


DEPENDENCY_GRAPH = {
    "kernel":     [],
    "bootloader": [],
    "rootfs":     [],
    "boot":       ["kernel"],
    "image":      ["boot", "bootloader", "rootfs"],
}


def _topo_sort(graph: dict, target: str) -> list:
    """拓扑排序，返回 target 及其全部依赖的构建顺序。"""
    visited = set()
    order = []

    def visit(node):
        if node in visited:
            return
        visited.add(node)
        for dep in graph.get(node, []):
            visit(dep)
        order.append(node)

    visit(target)
    return order


class BuildEngine:
    def __init__(self, config: dict, project_dir: Path = None):
        self.config = config
        self.project_dir = project_dir or Path.cwd()
        self.docker = DockerRunner(self.project_dir)
        self.source = SourceManager(self.project_dir / "sources")
        self.cache = BuildCache(config)
        self._outputs = {}

    def build(self, target: str = "image"):
        for component in _topo_sort(DEPENDENCY_GRAPH, target):
            if self.cache.is_up_to_date(component):
                log.info(f"  {component}: 无变更，跳过")
                continue

            log.info(f"  {component}: 开始构建...")
            builder = self._get_builder(component)
            outputs = builder.build(self.config)
            self._outputs[component] = outputs
            self.cache.store(component)
            log.info(f"  {component}: 完成")

    def _get_builder(self, component: str):
        platform = self.config["platform"]
        module_path = f"builder.platforms.{platform}"
        mod = importlib.import_module(module_path)
        return mod.create_builder(component, self.docker, self.source)
```

- [ ] **Step 7: 编写 BuildCache 测试**

```python
# tests/builder/test_cache.py

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from builder.cache import BuildCache


class TestBuildCache:
    def test_not_up_to_date_when_no_hash_file(self):
        config = {"board": "test-board", "product": "default", "variant": "release"}
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(BuildCache, '__init__', lambda self, cfg: None):
                cache = BuildCache.__new__(BuildCache)
                cache.config = config
                cache.target_dir = Path(tmpdir) / "test-board" / "default" / "release"
                assert not cache.is_up_to_date("kernel")

    def test_up_to_date_when_hash_matches(self):
        config = {"board": "test-board", "product": "default", "variant": "release",
                  "platform": "rockchip", "soc": "rk3566"}
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = BuildCache.__new__(BuildCache)
            cache.config = config
            cache.target_dir = Path(tmpdir) / "test-board" / "default" / "release"
            # 先 store
            cache.store("kernel")
            # 再检查
            assert cache.is_up_to_date("kernel")

    def test_not_up_to_date_when_config_changes(self):
        config1 = {"board": "test", "product": "default", "variant": "release",
                   "platform": "rockchip", "soc": "rk3566",
                   "kernel": {"defconfig": "defconfig_a"}}
        config2 = {"board": "test", "product": "default", "variant": "release",
                   "platform": "rockchip", "soc": "rk3566",
                   "kernel": {"defconfig": "defconfig_b"}}
        with tempfile.TemporaryDirectory() as tmpdir:
            cache1 = BuildCache.__new__(BuildCache)
            cache1.config = config1
            cache1.target_dir = Path(tmpdir) / "test" / "default" / "release"
            cache1.store("kernel")

            cache2 = BuildCache.__new__(BuildCache)
            cache2.config = config2
            cache2.target_dir = cache1.target_dir
            assert not cache2.is_up_to_date("kernel")
```

- [ ] **Step 8: 运行测试**

Run: `python3 -m pytest tests/builder/test_cache.py -v`
Expected: ALL PASS

- [ ] **Step 9: Commit**

```bash
git add builder/docker.py builder/source.py builder/cache.py builder/base.py builder/chroot.py builder/engine.py tests/builder/test_cache.py
git commit -m "feat(builder): 构建引擎基础设施 — DockerRunner, SourceManager, BuildCache, ComponentBuilder, ChrootContext"
```

---

## Task 5: Rockchip 平台策略类

**Files:**
- Create: `builder/platforms/rockchip/__init__.py`
- Create: `builder/platforms/rockchip/kernel.py`
- Create: `builder/platforms/rockchip/bootloader.py`
- Create: `builder/platforms/rockchip/rootfs.py`
- Create: `builder/platforms/rockchip/image.py`

- [ ] **Step 1: 实现 Rockchip 工厂函数**

```python
# builder/platforms/rockchip/__init__.py
"""Rockchip 平台构建策略工厂。"""

from builder.docker import DockerRunner
from builder.source import SourceManager


def create_builder(component: str, docker: DockerRunner, source: SourceManager):
    if component == "kernel":
        from builder.platforms.rockchip.kernel import RockchipKernelBuilder
        return RockchipKernelBuilder(docker, source)
    elif component == "bootloader":
        from builder.platforms.rockchip.bootloader import RockchipBootloaderBuilder
        return RockchipBootloaderBuilder(docker, source)
    elif component in ("rootfs", "boot"):
        from builder.platforms.rockchip.rootfs import RockchipRootfsBuilder
        return RockchipRootfsBuilder(docker, source)
    elif component == "image":
        from builder.platforms.rockchip.image import RockchipImageBuilder
        return RockchipImageBuilder(docker, source)
    else:
        raise ValueError(f"未知组件: {component}")
```

- [ ] **Step 2: 实现 RockchipKernelBuilder**

替代 `kernel/rockchip/build.sh` + `build/kernel_build.bzl` 中的逻辑。

```python
# builder/platforms/rockchip/kernel.py
"""Rockchip 内核构建策略 — 替代 kernel/rockchip/build.sh"""

from pathlib import Path
from builder.base import ComponentBuilder


class RockchipKernelBuilder(ComponentBuilder):
    component = "kernel"
    ARCH = "arm64"
    CROSS = "aarch64-linux-gnu-"

    def configure(self, src_dir: Path, config: dict):
        defconfig = config["kernel"]["defconfig"]
        self.make(src_dir, [defconfig], arch=self.ARCH, cross=self.CROSS)

    def compile(self, src_dir: Path, config: dict):
        jobs = config.get("jobs", 0)
        self.make(src_dir, ["Image", "dtbs", "modules"],
                  arch=self.ARCH, cross=self.CROSS, jobs=jobs,
                  extra=["KCFLAGS=-Wno-error"])

        # 安装模块 (strip)
        modules_staging = src_dir / "_modules_staging"
        modules_staging.mkdir(exist_ok=True)
        self.make(src_dir, ["modules_install"],
                  arch=self.ARCH, cross=self.CROSS,
                  extra=[f"INSTALL_MOD_PATH={modules_staging}", "INSTALL_MOD_STRIP=1"])

    def collect(self, src_dir: Path, config: dict) -> dict:
        dts_dir = config["kernel"].get("dts_dir", "rockchip")
        dts = config["kernel"]["dts"]
        return {
            "image": src_dir / f"arch/{self.ARCH}/boot/Image",
            "dtb": src_dir / f"arch/{self.ARCH}/boot/dts/{dts_dir}/{dts}.dtb",
            "modules": src_dir / "_modules_staging",
            "dtbos": src_dir / f"arch/{self.ARCH}/boot/dts/{dts_dir}/overlay",
        }
```

- [ ] **Step 3: 实现 RockchipBootloaderBuilder**

替代 `bootloader/rockchip/build.sh` + `build/bootloader_build.bzl`。核心改进：用 `configparser` 替代 `grep|awk|sed|cut` 链。

```python
# builder/platforms/rockchip/bootloader.py
"""Rockchip Bootloader 构建策略 — 替代 bootloader/rockchip/build.sh"""

import configparser
import shutil
from pathlib import Path
from builder.base import ComponentBuilder


class RockchipBootloaderBuilder(ComponentBuilder):
    component = "bootloader"
    ARCH = "arm"
    CROSS = "aarch64-linux-gnu-"

    def configure(self, src_dir: Path, config: dict):
        defconfig = config["bootloader"]["defconfig"]
        self.make(src_dir, [defconfig], arch=self.ARCH, cross=self.CROSS)

    def compile(self, src_dir: Path, config: dict):
        firmware_dir = self.source.ensure_firmware("rockchip", config)
        ini_prefix = config["rkbin"]["ini_prefix"]
        trust_prefix = config["rkbin"].get("trust_ini_prefix", ini_prefix)
        jobs = config.get("jobs", 0)

        # 解析 RKTRUST INI — 提取 BL31/BL32
        trust_ini = firmware_dir / "RKTRUST" / f"{trust_prefix}TRUST.ini"
        bl31, bl32 = self._parse_trust_ini(trust_ini, firmware_dir)

        shutil.copy(bl31, src_dir / "bl31.elf")
        extra = [f"BL31={src_dir / 'bl31.elf'}"]
        if bl32:
            shutil.copy(bl32, src_dir / "tee.bin")
            extra.append(f"TEE={src_dir / 'tee.bin'}")

        # 编译 U-Boot → u-boot.itb
        self.make(src_dir, ["u-boot.itb"],
                  arch=self.ARCH, cross=self.CROSS, jobs=jobs, extra=extra)

        # 解析 RKBOOT INI — 生成 idbloader.img
        loader_ini = firmware_dir / "RKBOOT" / f"{ini_prefix}MINIALL.ini"
        ddr_bin, spl_bin = self._parse_loader_ini(loader_ini, firmware_dir)
        self.docker.run([
            str(src_dir / "tools/mkimage"), "-n", "rk3568", "-T", "rksd",
            "-d", f"{ddr_bin}:{spl_bin}", str(src_dir / "idbloader.img"),
        ])

        # 生成 miniloader.bin
        self.docker.run([
            str(firmware_dir / "tools/boot_merger"), str(loader_ini),
        ], cwd=str(firmware_dir))

    def _parse_trust_ini(self, ini_path: Path, fw_dir: Path):
        cfg = configparser.ConfigParser()
        cfg.read(ini_path)
        bl31_rel = cfg.get("BL31_OPTION", "PATH", fallback="")
        bl31 = fw_dir / bl31_rel if bl31_rel else None
        bl32_rel = cfg.get("BL32_OPTION", "PATH", fallback="")
        bl32 = (fw_dir / bl32_rel) if bl32_rel else None
        return bl31, bl32

    def _parse_loader_ini(self, ini_path: Path, fw_dir: Path):
        cfg = configparser.ConfigParser()
        cfg.read(ini_path)
        ddr_rel = cfg.get("LOADER_OPTION", "FlashData", fallback="")
        spl_rel = cfg.get("LOADER_OPTION", "FlashBoot", fallback="")
        return fw_dir / ddr_rel, fw_dir / spl_rel

    def collect(self, src_dir: Path, config: dict) -> dict:
        firmware_dir = self.source.ensure_firmware("rockchip", config)
        ini_prefix = config["rkbin"]["ini_prefix"]
        # miniloader 输出在 firmware_dir 下，文件名包含版本号
        miniloader_candidates = list(firmware_dir.glob(f"{ini_prefix}_loader_v*.bin"))
        miniloader = miniloader_candidates[0] if miniloader_candidates else firmware_dir / "miniloader.bin"
        return {
            "bootloader": src_dir / "u-boot.itb",
            "idbloader": src_dir / "idbloader.img",
            "miniloader": miniloader,
        }
```

- [ ] **Step 4: 实现 RockchipRootfsBuilder**

替代 `rootfs/rockchip/build_base.sh` + `build_customize.sh`。

```python
# builder/platforms/rockchip/rootfs.py
"""Rockchip Rootfs 构建策略 — 替代 build_base.sh + build_customize.sh"""

import shutil
import tempfile
from pathlib import Path
from builder.base import ComponentBuilder
from builder.chroot import ChrootContext


class RockchipRootfsBuilder(ComponentBuilder):
    component = "rootfs"

    def configure(self, src_dir: Path, config: dict):
        pass  # rootfs 无 configure 步骤

    def compile(self, src_dir: Path, config: dict):
        self._work_dir = Path(tempfile.mkdtemp(prefix="flange-rootfs-"))
        rootfs_dir = self._work_dir / "rootfs"
        rootfs_dir.mkdir()

        tarball = config["rootfs"]["url"]  # 由 source manager 下载后的本地路径
        # 如果是远程 URL，source manager 应已下载
        tarball_path = self.source.ensure_rootfs_tarball(config)

        # Phase 1: Base rootfs
        self.docker.run_privileged(["tar", "xf", str(tarball_path), "-C", str(rootfs_dir)])
        self.docker.run_privileged(
            ["cp", "/usr/bin/qemu-aarch64-static", str(rootfs_dir / "usr/bin/")])

        with ChrootContext(rootfs_dir, self.docker) as chroot:
            apt_cache = rootfs_dir / "var/cache/apt/archives"
            apt_cache.mkdir(parents=True, exist_ok=True)
            chroot.bind_mount("/cache/apt", apt_cache)
            chroot.run(["apt-get", "update"])
            chroot.run(["apt-get", "install", "-y", "--no-install-recommends"]
                       + config["rootfs"]["packages"])
            chroot.run(["apt-get", "clean"])

        # Phase 2: Customize
        board = config["board"]
        overlay_dir = Path(f"board/{board}/overlay")
        if overlay_dir.exists():
            self.docker.run_privileged(
                ["cp", "-a", f"{overlay_dir}/.", str(rootfs_dir)])

        # Phase 3: 压缩
        self._output = self._work_dir / "rootfs.tar.gz"
        self.docker.run_privileged(
            ["tar", "-czf", str(self._output), "-C", str(rootfs_dir), "."])

    def collect(self, src_dir: Path, config: dict) -> dict:
        return {"rootfs": self._output}
```

- [ ] **Step 5: 实现 RockchipImageBuilder**

替代 `image/rockchip/build_boot.sh` + `build_image.sh`。

```python
# builder/platforms/rockchip/image.py
"""Rockchip 镜像组装策略 — 替代 build_boot.sh + build_image.sh"""

import tempfile
from pathlib import Path
from builder.base import ComponentBuilder
from builder.partition.rockchip import RockchipPartitionConverter


class RockchipImageBuilder(ComponentBuilder):
    component = "image"
    SECTOR_SIZE = 512
    IDBLOADER_SECTOR = 64
    ROOTFS_PARTUUID = "614e0000-0000-4000-8000-000000000000"

    def configure(self, src_dir: Path, config: dict):
        pass

    def compile(self, src_dir: Path, config: dict):
        self._work_dir = Path(tempfile.mkdtemp(prefix="flange-image-"))
        # 注意: 在完整 engine 流程中，依赖组件的产物会通过 engine._outputs 传入
        # 这里假设产物已在 target/ 目录
        board = config["board"]
        product = config.get("product", "default")
        variant = config.get("variant", "release")
        target_base = Path("target") / board / product / variant

        # 生成 parameter.txt
        partitions = config.get("partitions", {})
        if partitions:
            converter = RockchipPartitionConverter()
            param_txt = converter.convert(partitions)
            param_path = self._work_dir / "parameter.txt"
            param_path.write_text(param_txt)

        # boot 分区构建
        boot_img = self._build_boot(config)

        # 磁盘镜像组装
        self._raw_img = self._assemble_image(boot_img, config)

    def _build_boot(self, config: dict) -> Path:
        boot_dir = self._work_dir / "boot_content"
        boot_dir.mkdir()
        # 从 kernel 产物复制
        # ... (ext4 mkfs + losetup + copy + umount)
        boot_img = self._work_dir / "boot.img"
        size_mb = config.get("boot", {}).get("size_mb", 256)
        self.docker.run_privileged([
            "dd", "if=/dev/zero", f"of={boot_img}", "bs=1M", f"count={size_mb}"])
        self.docker.run_privileged(["mkfs.ext4", "-F", "-L", "boot", str(boot_img)])
        return boot_img

    def _assemble_image(self, boot_img: Path, config: dict) -> Path:
        raw_img = self._work_dir / "raw.img"
        partitions = config.get("partitions", {})
        entries = partitions.get("entries", [])

        # 计算总镜像大小
        last = entries[-1] if entries else {}
        if last.get("size") == "remaining":
            # 默认 4G
            total_bytes = 4 * 1024 * 1024 * 1024
        else:
            total_bytes = 4 * 1024 * 1024 * 1024

        self.docker.run_privileged([
            "dd", "if=/dev/zero", f"of={raw_img}", "bs=1", "count=0", f"seek={total_bytes}"])
        self.docker.run_privileged(["parted", "-s", str(raw_img), "mklabel", "gpt"])

        # 写入 idbloader + bootloader + boot + rootfs (dd)
        # ... 详细的 dd 命令序列与 build_image.sh 逻辑一致
        return raw_img

    def collect(self, src_dir: Path, config: dict) -> dict:
        return {"image": self._raw_img}
```

- [ ] **Step 6: Commit**

```bash
git add builder/platforms/rockchip/
git commit -m "feat(builder): Rockchip 平台策略类 — 替代全部 shell 构建脚本"
```

---

## Task 6: 分区表系统 + Flash 生成

**Files:**
- Create: `builder/partition/__init__.py`
- Create: `builder/partition/rockchip.py`
- Create: `builder/partition/generic.py`
- Create: `builder/flash.py`
- Create: `tests/builder/test_partition.py`
- Create: `tests/builder/test_flash.py`

- [ ] **Step 1: 实现分区表中间格式**

```python
# builder/partition/__init__.py
"""分区表中间格式定义。"""

from dataclasses import dataclass, field


@dataclass
class Partition:
    name: str
    size: str           # "0x2000" (sectors), "4M", "remaining"
    type: str           # "raw", "ext4", "fat32"
    offset: str = ""    # "0x40" (sectors)

@dataclass
class PartitionTable:
    format: str = "gpt"
    sector_size: int = 512
    entries: list = field(default_factory=list)

    @classmethod
    def from_config(cls, config: dict) -> 'PartitionTable':
        table = cls(
            format=config.get("format", "gpt"),
            sector_size=config.get("sector_size", 512),
        )
        for entry in config.get("entries", []):
            table.entries.append(Partition(
                name=entry["name"],
                size=entry["size"],
                type=entry["type"],
                offset=entry.get("offset", ""),
            ))
        return table
```

- [ ] **Step 2: 实现 Rockchip 分区转换器**

```python
# builder/partition/rockchip.py
"""Rockchip parameter.txt 生成器。"""

from builder.partition import PartitionTable


class RockchipPartitionConverter:
    def convert(self, partition_config: dict) -> str:
        table = PartitionTable.from_config(partition_config)
        lines = [
            "FIRMWARE_VER:1.0",
            "MACHINE_MODEL:rockchip",
            "MACHINE_ID:007",
            "MANUFACTURER:flange",
            "MAGIC:0x5041524B",
            "ATAG:0x00200800",
            "MACHINE:rockchip",
            "CHECK_MASK:0x80",
            "PWR_HLD:0,0,A,0,1",
            f"TYPE: {table.format.upper()}",
            f"CMDLINE:mtdparts=rk29xxnand:{self._build_mtdparts(table)}",
        ]
        return "\n".join(lines) + "\n"

    def _build_mtdparts(self, table: PartitionTable) -> str:
        parts = []
        for entry in table.entries:
            if entry.type == "raw" and entry.name == "idbloader":
                continue  # idbloader 写在固定 sector 64，不进 mtdparts
            if entry.size == "remaining":
                parts.append(f"-@{entry.offset}({entry.name}:grow)")
            else:
                parts.append(f"{entry.size}@{entry.offset}({entry.name})")
        return ",".join(parts)
```

- [ ] **Step 3: 实现 Flash 生成器**

```python
# builder/flash.py
"""flash.sh 自动生成。"""

from pathlib import Path


class FlashGenerator:
    def generate(self, config: dict, target_dir: Path):
        flash_tool = config.get("flash_tool", "upgrade_tool")
        board = config["board"]
        product = config.get("product", "default")
        variant = config.get("variant", "release")

        script = f"""#!/bin/bash
# 自动生成 by flange — 请勿手动编辑
# board: {board}  product: {product}  variant: {variant}
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FLASH_TOOL="{flash_tool}"

flash_bootloader() {{
    echo "刷写 bootloader..."
    "$FLASH_TOOL" db "$SCRIPT_DIR/bootloader/miniloader.bin"
    sleep 1
    "$FLASH_TOOL" wl 0x40 "$SCRIPT_DIR/bootloader/idbloader.img"
    "$FLASH_TOOL" wl 0x4000 "$SCRIPT_DIR/bootloader/bootloader.img"
}}

flash_kernel() {{
    echo "刷写 boot 分区..."
    "$FLASH_TOOL" wl 0x8000 "$SCRIPT_DIR/image/boot.img"
}}

flash_rootfs() {{
    echo "刷写 rootfs..."
    "$FLASH_TOOL" wl 0x40000 "$SCRIPT_DIR/image/rootfs.img"
}}

flash_all() {{
    flash_bootloader
    flash_kernel
    flash_rootfs
    echo "刷写完成，重启设备..."
    "$FLASH_TOOL" rd
}}

case "${{1:-all}}" in
    bootloader) flash_bootloader ;;
    kernel)     flash_kernel ;;
    rootfs)     flash_rootfs ;;
    all)        flash_all ;;
    *)          echo "用法: $0 [bootloader|kernel|rootfs|all]" ;;
esac
"""
        flash_sh = target_dir / "flash.sh"
        flash_sh.parent.mkdir(parents=True, exist_ok=True)
        flash_sh.write_text(script)
        flash_sh.chmod(0o755)
```

- [ ] **Step 4: 编写分区表测试**

```python
# tests/builder/test_partition.py

from builder.partition import PartitionTable, Partition
from builder.partition.rockchip import RockchipPartitionConverter


class TestPartitionTable:
    def test_from_config(self):
        config = {
            "format": "gpt",
            "entries": [
                {"name": "boot", "offset": "0x8000", "size": "0x20000", "type": "ext4"},
                {"name": "rootfs", "offset": "0x40000", "size": "remaining", "type": "ext4"},
            ],
        }
        table = PartitionTable.from_config(config)
        assert table.format == "gpt"
        assert len(table.entries) == 2
        assert table.entries[0].name == "boot"
        assert table.entries[1].size == "remaining"


class TestRockchipConverter:
    def test_generates_parameter_txt(self):
        config = {
            "format": "gpt",
            "entries": [
                {"name": "idbloader", "offset": "0x40", "size": "0x2000", "type": "raw"},
                {"name": "uboot", "offset": "0x4000", "size": "0x2000", "type": "raw"},
                {"name": "boot", "offset": "0x8000", "size": "0x20000", "type": "ext4"},
                {"name": "rootfs", "offset": "0x40000", "size": "0x200000", "type": "ext4"},
                {"name": "userdata", "offset": "0x240000", "size": "remaining", "type": "ext4"},
            ],
        }
        converter = RockchipPartitionConverter()
        result = converter.convert(config)
        assert "TYPE: GPT" in result
        assert "CMDLINE:mtdparts=rk29xxnand:" in result
        assert "uboot" in result
        assert "boot" in result
        assert "rootfs" in result
        assert "(userdata:grow)" in result
        # idbloader 不应出现在 mtdparts
        lines = result.split("\n")
        cmdline = [l for l in lines if l.startswith("CMDLINE:")][0]
        assert "idbloader" not in cmdline
```

- [ ] **Step 5: 编写 Flash 测试**

```python
# tests/builder/test_flash.py

import tempfile
from pathlib import Path

from builder.flash import FlashGenerator


class TestFlashGenerator:
    def test_generates_executable_script(self):
        config = {
            "board": "radxa-zero3w",
            "product": "default",
            "variant": "release",
            "flash_tool": "upgrade_tool",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir)
            gen = FlashGenerator()
            gen.generate(config, target_dir)

            flash_sh = target_dir / "flash.sh"
            assert flash_sh.exists()
            assert flash_sh.stat().st_mode & 0o111  # executable

            content = flash_sh.read_text()
            assert "upgrade_tool" in content
            assert "radxa-zero3w" in content
            assert "flash_bootloader" in content
            assert "flash_kernel" in content
            assert "flash_rootfs" in content
            assert "flash_all" in content

    def test_uses_config_flash_tool(self):
        config = {
            "board": "test", "product": "default", "variant": "release",
            "flash_tool": "qdl",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = FlashGenerator()
            gen.generate(config, Path(tmpdir))
            content = (Path(tmpdir) / "flash.sh").read_text()
            assert 'FLASH_TOOL="qdl"' in content
```

- [ ] **Step 6: 运行测试**

Run: `python3 -m pytest tests/builder/test_partition.py tests/builder/test_flash.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add builder/partition/ builder/flash.py tests/builder/test_partition.py tests/builder/test_flash.py
git commit -m "feat(builder): 分区表系统（中间格式→Rockchip parameter.txt）+ flash.sh 自动生成"
```

---

## Task 7: CLI 重写 (envsetup.sh)

**Files:**
- Modify: `envsetup.sh`

- [ ] **Step 1: 重写 envsetup.sh**

完整替换 `envsetup.sh`。核心变更：
- `lunch` 支持 `<board>-<product>-<variant>` 完整格式和部分覆盖
- `.flange/current_config` JSON 持久化
- `flange build` 调用 Python 构建引擎代替 Bazel
- `flange docker build/rebuild/status` 子命令
- 自动检测并构建 Docker 镜像

```bash
#!/bin/bash
# flange 开发环境初始化脚本
#
# 用法: source envsetup.sh

# --- 项目根目录 ---
if [[ -n "${BASH_SOURCE[0]}" ]]; then
    FLANGE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
elif [[ -n "$0" ]]; then
    FLANGE_DIR="$(cd "$(dirname "$0")" && pwd)"
fi
export FLANGE_DIR

# --- 颜色 ---
_FLANGE_RED='\033[0;31m'
_FLANGE_GREEN='\033[0;32m'
_FLANGE_YELLOW='\033[1;33m'
_FLANGE_BLUE='\033[0;34m'
_FLANGE_NC='\033[0m'

_flange_info()  { echo -e "${_FLANGE_GREEN}[INFO]${_FLANGE_NC} $*"; }
_flange_warn()  { echo -e "${_FLANGE_YELLOW}[WARN]${_FLANGE_NC} $*"; }
_flange_error() { echo -e "${_FLANGE_RED}[ERROR]${_FLANGE_NC} $*"; }
_flange_step()  { echo -e "${_FLANGE_BLUE}==>${_FLANGE_NC} $*"; }

# --- 状态目录 ---
_FLANGE_STATE_DIR="$FLANGE_DIR/.flange"
_FLANGE_CONFIG_FILE="$_FLANGE_STATE_DIR/current_config"
mkdir -p "$_FLANGE_STATE_DIR"

# --- 恢复上次 lunch 状态 ---
_flange_load_config() {
    if [[ -f "$_FLANGE_CONFIG_FILE" ]]; then
        FLANGE_BOARD=$(python3 -c "import json; c=json.load(open('$_FLANGE_CONFIG_FILE')); print(c['board'])")
        FLANGE_PRODUCT=$(python3 -c "import json; c=json.load(open('$_FLANGE_CONFIG_FILE')); print(c.get('product','default'))")
        FLANGE_VARIANT=$(python3 -c "import json; c=json.load(open('$_FLANGE_CONFIG_FILE')); print(c.get('variant','release'))")
        export FLANGE_BOARD FLANGE_PRODUCT FLANGE_VARIANT
    fi
}

# --- lunch ---
lunch() {
    local target="$1"
    local board product variant

    if [[ -z "$target" && -z "$2" ]]; then
        # 交互式: 列出所有可用 target
        echo ""
        echo "  可用配置:"
        local targets
        targets=$(cd "$FLANGE_DIR" && python3 -c "
from config.query import get_valid_targets
for i, t in enumerate(get_valid_targets(), 1):
    print(f'    {i}. {t}')
")
        echo "$targets"
        echo ""
        read -r -p "  请选择: " choice
        target=$(cd "$FLANGE_DIR" && python3 -c "
from config.query import get_valid_targets
targets = get_valid_targets()
try:
    print(targets[int('$choice') - 1])
except (ValueError, IndexError):
    print('')
")
        if [[ -z "$target" ]]; then
            _flange_error "无效选择"
            return 1
        fi
    fi

    # 处理 --variant=xxx, --product=xxx 部分覆盖
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --variant=*) variant="${1#*=}"; shift ;;
            --product=*) product="${1#*=}"; shift ;;
            *) target="$1"; shift ;;
        esac
    done

    # 如果只指定了部分覆盖，沿用当前配置
    if [[ -z "$target" ]]; then
        target="${FLANGE_BOARD}"
    fi

    # 解析 target → board/product/variant
    local parsed
    parsed=$(cd "$FLANGE_DIR" && python3 -c "
import json
from config.query import parse_target
try:
    r = parse_target('$target')
    print(json.dumps(r))
except ValueError as e:
    print(f'ERROR:{e}')
")
    if [[ "$parsed" == ERROR:* ]]; then
        _flange_error "${parsed#ERROR:}"
        return 1
    fi

    board=$(echo "$parsed" | python3 -c "import json,sys; print(json.load(sys.stdin)['board'])")
    [[ -z "$product" ]] && product=$(echo "$parsed" | python3 -c "import json,sys; print(json.load(sys.stdin)['product'])")
    [[ -z "$variant" ]] && variant=$(echo "$parsed" | python3 -c "import json,sys; print(json.load(sys.stdin)['variant'])")

    export FLANGE_BOARD="$board"
    export FLANGE_PRODUCT="$product"
    export FLANGE_VARIANT="$variant"

    # 生成 FINAL_CONFIG 并持久化
    (cd "$FLANGE_DIR" && python3 -c "
import json
from config.registry import resolve_config
config = resolve_config('$board', '$product', '$variant')
config['product'] = '$product'
config['variant'] = '$variant'
with open('$_FLANGE_CONFIG_FILE', 'w') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)
")

    _flange_info "已选择: $FLANGE_BOARD / $FLANGE_PRODUCT / $FLANGE_VARIANT"
}

# --- Docker ---
_flange_ensure_docker() {
    if ! docker info &>/dev/null; then
        _flange_error "Docker 未运行"
        return 1
    fi
    # 检查镜像是否存在，不存在则自动构建
    if ! docker compose -f "$FLANGE_DIR/docker-compose.yml" images build --quiet 2>/dev/null | grep -q .; then
        _flange_step "首次使用，构建 Docker 镜像..."
        (cd "$FLANGE_DIR" && docker compose build)
    fi
    return 0
}

_flange_docker_run() {
    (cd "$FLANGE_DIR" && docker compose run --rm build "$@")
}

# --- 子命令 ---
_flange_cmd_build() {
    local component="${1:-image}"
    _flange_step "构建 $component: $FLANGE_BOARD / $FLANGE_PRODUCT / $FLANGE_VARIANT"
    (cd "$FLANGE_DIR" && python3 -m builder.engine "$component")
}

_flange_cmd_flash() {
    local target_dir="$FLANGE_DIR/target/$FLANGE_BOARD/$FLANGE_PRODUCT/$FLANGE_VARIANT"
    local flash_sh="$target_dir/flash.sh"
    if [[ ! -f "$flash_sh" ]]; then
        _flange_error "未找到 flash.sh，请先 flange build"
        return 1
    fi
    _flange_step "刷写: $FLANGE_BOARD"
    "$flash_sh" "${1:-all}"
}

_flange_cmd_clean() {
    local target_dir="$FLANGE_DIR/target/$FLANGE_BOARD/$FLANGE_PRODUCT/$FLANGE_VARIANT"
    if [[ -d "$target_dir" ]]; then
        rm -rf "$target_dir"
        _flange_info "已清理: $target_dir"
    fi
}

_flange_cmd_status() {
    echo ""
    echo "  flange 构建状态"
    echo "  ─────────────────────────────"
    echo "  板级配置:  ${FLANGE_BOARD:-（未选择）}"
    echo "  产品:      ${FLANGE_PRODUCT:-—}"
    echo "  变体:      ${FLANGE_VARIANT:-—}"
    echo "  项目目录:  $FLANGE_DIR"
    echo ""
    if docker info &>/dev/null; then
        echo -e "  Docker:    ${_FLANGE_GREEN}运行中${_FLANGE_NC}"
    else
        echo -e "  Docker:    ${_FLANGE_RED}未运行${_FLANGE_NC}"
    fi
    if [[ -n "$FLANGE_BOARD" ]]; then
        local target_dir="$FLANGE_DIR/target/$FLANGE_BOARD/$FLANGE_PRODUCT/$FLANGE_VARIANT"
        echo ""
        echo "  产物目录: $target_dir"
        if [[ -d "$target_dir" ]]; then
            for comp in kernel bootloader rootfs image; do
                if [[ -d "$target_dir/$comp" ]]; then
                    echo -e "    $comp/ ${_FLANGE_GREEN}✓${_FLANGE_NC}"
                else
                    echo -e "    $comp/ ${_FLANGE_YELLOW}未构建${_FLANGE_NC}"
                fi
            done
        fi
    fi
    echo ""
}

_flange_cmd_shell() {
    _flange_step "进入构建环境 shell"
    _flange_docker_run bash
}

_flange_cmd_docker() {
    case "${1:-}" in
        build)   (cd "$FLANGE_DIR" && docker compose build) ;;
        rebuild) (cd "$FLANGE_DIR" && docker compose build --no-cache) ;;
        status)  (cd "$FLANGE_DIR" && docker compose images) ;;
        *)       echo "用法: flange docker [build|rebuild|status]" ;;
    esac
}

# --- 主入口 ---
flange() {
    local subcmd="$1"
    if [[ -z "$subcmd" ]]; then
        echo ""
        echo "  用法: flange <subcommand> [参数...]"
        echo ""
        echo "  构建:  build [component]   构建组件 (kernel/bootloader/rootfs/image)"
        echo "  刷写:  flash [component]   刷写到目标设备"
        echo "  工具:  sync               同步源码版本"
        echo "         shell              进入 Docker 构建环境"
        echo "         clean              清理构建产物"
        echo "         status             显示当前状态"
        echo "         docker [cmd]       管理 Docker 构建环境"
        echo ""
        echo "  当前: ${FLANGE_BOARD:-未选择} / ${FLANGE_PRODUCT:-—} / ${FLANGE_VARIANT:-—}"
        echo ""
        return 0
    fi
    shift
    case "$subcmd" in
        build)
            [[ -z "$FLANGE_BOARD" ]] && { _flange_error "请先 lunch"; return 1; }
            _flange_ensure_docker || return 1
            _flange_cmd_build "$@" ;;
        flash)
            [[ -z "$FLANGE_BOARD" ]] && { _flange_error "请先 lunch"; return 1; }
            _flange_cmd_flash "$@" ;;
        clean)
            [[ -z "$FLANGE_BOARD" ]] && { _flange_error "请先 lunch"; return 1; }
            _flange_cmd_clean "$@" ;;
        status) _flange_cmd_status ;;
        shell)
            _flange_ensure_docker || return 1
            _flange_cmd_shell "$@" ;;
        docker) _flange_cmd_docker "$@" ;;
        *) _flange_error "未知子命令: $subcmd"; flange; return 1 ;;
    esac
}

# --- 初始化 ---
_flange_load_config
_flange_info "flange 开发环境已加载"
if [[ -n "$FLANGE_BOARD" ]]; then
    _flange_info "当前配置: $FLANGE_BOARD / $FLANGE_PRODUCT / $FLANGE_VARIANT"
else
    echo "  执行 lunch 选择配置"
fi
```

- [ ] **Step 2: Commit**

```bash
git add envsetup.sh
git commit -m "feat(cli): 重写 envsetup.sh，支持 product/variant、.flange 持久化、docker 子命令"
```

---

## Task 8: Docker 迁移

**Files:**
- Modify: `docker/Dockerfile`
- Modify: `docker-compose.yml`

- [ ] **Step 1: 更新 Dockerfile — 删 Bazel, 加 Python builder**

在 `docker/Dockerfile` 中：
- 删除 bazelisk 安装部分
- 确保 python3 已安装（已有）
- 设置 PYTHONPATH

```dockerfile
FROM --platform=linux/amd64 ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

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

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

ENV PYTHONPATH=/workspace

WORKDIR /workspace
ENTRYPOINT ["entrypoint.sh"]
```

- [ ] **Step 2: 更新 docker-compose.yml**

```yaml
services:
  build:
    build:
      context: .
      dockerfile: docker/Dockerfile
    privileged: true
    volumes:
      - .:/workspace
      - ./sources:/workspace/sources
      - ./cache/apt:/cache/apt
      - ~/.ssh:/tmp/.ssh-host:ro
    working_dir: /workspace
```

删除的 volumes：
- `./output/bazel:/workspace/output/bazel`（Bazel output base）
- `./cache/bazelisk:/root/.cache/bazelisk`（Bazelisk 缓存）

- [ ] **Step 3: Commit**

```bash
git add docker/Dockerfile docker-compose.yml
git commit -m "chore(docker): 移除 Bazel 依赖，加 PYTHONPATH，更新 volume 映射"
```

---

## Task 9: 删除 Bazel 文件 + 清理

**Files:**
- Delete: 47 个 Bazel 相关文件
- Delete: `toolchain/` 目录
- Delete: shell 构建脚本

- [ ] **Step 1: 删除全部 Bazel 文件**

```bash
cd /Users/eki/Project/Embedded_Project/flange

# Bazel 项目文件
rm -f MODULE.bazel MODULE.bazel.lock .bazelrc .bazelversion BUILD.bazel

# build/ 下所有 .bzl 和 BUILD.bazel
rm -f build/*.bzl build/BUILD.bazel

# 组件目录的 BUILD.bazel 和 .sh
rm -f kernel/BUILD.bazel kernel/rockchip/BUILD.bazel kernel/rockchip/build.sh
rm -f bootloader/BUILD.bazel bootloader/rockchip/BUILD.bazel bootloader/rockchip/build.sh
rm -f rootfs/BUILD.bazel rootfs/rockchip/BUILD.bazel rootfs/rockchip/build_base.sh rootfs/rockchip/build_customize.sh
rm -f image/BUILD.bazel image/rockchip/BUILD.bazel image/rockchip/build_boot.sh image/rockchip/build_image.sh image/rockchip/parameter.txt

# 板级 BUILD.bazel 和旧 .bzl 配置
rm -f board/radxa-zero3w/BUILD.bazel board/radxa-zero3w/board.bzl
rm -f board/neons-core3566-nanob/BUILD.bazel board/neons-core3566-nanob/board.bzl
rm -f board/tspi-rk3566/BUILD.bazel board/tspi-rk3566/board.bzl
rm -f board/orangepi-cm4/BUILD.bazel board/orangepi-cm4/board.bzl

# 平台 BUILD.bazel 和旧 .bzl
rm -f platform/rockchip/BUILD.bazel platform/rockchip/config.bzl
rm -f platform/rockchip/rk3566/config.bzl
test -f platform/rockchip/rk3566/BUILD.bazel && rm -f platform/rockchip/rk3566/BUILD.bazel

# 其他
rm -f packages/BUILD.bazel app/adbd/BUILD.bazel

# Bazel 工具链 (整个目录)
rm -rf toolchain/

# Bazel 缓存和产物
rm -rf output/bazel/ cache/bazelisk/
```

- [ ] **Step 2: 清理空目录**

如果 `build/` 目录已空（所有 .bzl 已删），删除整个目录：

```bash
rmdir build 2>/dev/null || true
```

保留的目录（只剩 patches 和数据文件）：
- `kernel/rockchip/patches/` — 保留
- `bootloader/rockchip/patches/` — 保留
- `board/*/overlay/` — 保留
- `board/*/patches/` — 保留

注意：`kernel/rockchip/patches/`、`bootloader/rockchip/patches/` 现在应迁移到 `platform/rockchip/patches/kernel/` 和 `platform/rockchip/patches/bootloader/`。

```bash
# 迁移平台级补丁到新位置
mkdir -p platform/rockchip/patches/kernel
mkdir -p platform/rockchip/patches/bootloader
test -d kernel/rockchip/patches && cp -r kernel/rockchip/patches/* platform/rockchip/patches/kernel/ 2>/dev/null || true
test -d bootloader/rockchip/patches && cp -r bootloader/rockchip/patches/* platform/rockchip/patches/bootloader/ 2>/dev/null || true

# 删除旧组件目录（如果只剩空目录）
rm -rf kernel/rockchip/patches kernel/rockchip kernel
rm -rf bootloader/rockchip/patches bootloader/rockchip bootloader
rm -rf rootfs/rockchip rootfs
rm -rf image/rockchip image
```

- [ ] **Step 3: 运行测试确认无破坏**

Run: `python3 -m pytest tests/ -v`
Expected: ALL PASS — 配置测试和 builder 测试不依赖 Bazel 文件

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: 删除全部 Bazel/Starlark/Shell 文件，迁移平台补丁到新目录结构"
```

---

## Task 10: 集成验证 + 文档更新

**Files:**
- Modify: `CLAUDE.md`
- Modify: `ProjectSpec.md`（如需更新构建系统章节）

- [ ] **Step 1: 验证配置全链路**

```bash
cd /Users/eki/Project/Embedded_Project/flange
python3 -c "
from config.registry import resolve_config
import json

# 验证 4 块板子的完整配置解析
for board in ['radxa-zero3w', 'neons-core3566-nanob', 'tspi-rk3566', 'orangepi-cm4']:
    config = resolve_config(board, 'default', 'debug')
    print(f'{board}:')
    print(f'  platform={config[\"platform\"]} arch={config[\"arch\"]}')
    print(f'  kernel.dts={config[\"kernel\"][\"dts\"]}')
    print(f'  packages={len(config[\"rootfs\"][\"packages\"])} 个')
    print(f'  partitions={len(config[\"partitions\"][\"entries\"])} 个分区')
    # debug 变体应包含调试包
    assert 'gdb' in config['rootfs']['packages'], f'{board} debug 缺少 gdb'
    print(f'  debug packages OK ✓')
    print()

# 验证 release 变体不含调试包
config = resolve_config('radxa-zero3w', 'default', 'release')
assert 'gdb' not in config['rootfs']['packages']
print('release variant: no debug packages ✓')
"
```
Expected: 4 块板子全部通过，debug/release 包列表正确

- [ ] **Step 2: 运行完整测试套件**

Run: `python3 -m pytest tests/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 3: 更新 CLAUDE.md**

更新 CLAUDE.md 中的关键约定：

将 **Bazel 统一构建** 相关描述替换为 Python 构建引擎描述：
- 构建用 `flange build`，不再是 `bazel build`
- 刷写用 `flange flash`
- 配置通过 `lunch` 选择，产物在 `target/<board>/<product>/<variant>/`

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: 更新 CLAUDE.md，反映 Python 构建系统架构"
```

---

## 执行顺序总结

```
Task 1  → Python 脚手架                     (独立)
Task 2  → config/merge.py + 测试            (依赖 Task 1)
Task 3  → config/registry.py + 板级配置迁移  (依赖 Task 2)
Task 4  → builder 基础设施                   (依赖 Task 1)
Task 5  → Rockchip 平台策略类                (依赖 Task 4)
Task 6  → 分区表 + Flash 生成               (依赖 Task 4)
Task 7  → CLI (envsetup.sh) 重写             (依赖 Task 3)
Task 8  → Docker 迁移                        (依赖 Task 5)
Task 9  → 删除 Bazel 文件                   (依赖 Task 3,5,7,8)
Task 10 → 集成验证                           (依赖全部)
```

可并行的任务对：
- Task 2 + Task 4（配置引擎和构建基础设施无依赖）
- Task 5 + Task 6（平台策略和分区表无依赖）
- Task 7 + Task 8（CLI 和 Docker 无依赖）
