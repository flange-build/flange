# CLAUDE.md — flange AI Agent 指引

## 项目简介

flange 是一个嵌入式 Linux 系统构建框架，基于 ubuntu-base 构建，类似 Buildroot/Yocto 但更快速、更可预测。

## 项目规格

**所有工作必须遵循 [ProjectSpec.md](./ProjectSpec.md)**。这是项目的权威规格文档，涵盖：

- **项目目标**：核心目标与核心优势定义
- **架构设计**：Docker 容器化构建模型、支持平台、组件级构建与刷写架构
- **编码规范**：Shell、Makefile、C/C++、Python 各语言编码风格
- **开发规范**：目录结构、Git 分支策略、构建系统、部署刷写约定
- **维护规范**：安全要求、文档语言、规范执行机制

在编写或修改代码前，先阅读 ProjectSpec.md 中对应章节。

## 语言要求

- 所有文档、注释、commit message 使用**中文**
- 代码标识符使用**英文**
- 专业术语保留英文，首次出现时标注中文释义

## 工作流程

本项目使用 OpenSpec 进行变更管理：
1. **探索** (`/opsx:explore`) — 思考与调研
2. **提案** (`/opsx:propose`) — 创建变更方案
3. **实施** (`/opsx:apply`) — 按任务执行
4. **归档** (`/opsx:archive`) — 完成后归档

## 关键约定

- **Python 统一构建**：构建用 `flange build`，刷写用 `flange flash`，配置通过 `lunch` 选择
- **Docker 构建**：所有编译构建在 Docker 容器内完成，宿主机不做编译环境要求
- **宿主机刷写**：镜像刷写在宿主机执行，通过 USB 连接目标设备
- **依赖自动推断**：组件间依赖由构建引擎自动推断（builder/engine.py），变更后基于内容哈希仅增量重建
- **多平台支持**：Rockchip、Allwinner、Qualcomm、Amlogic 等平台各有对应的刷写工具
- 构建规则使用 Python 编写（builder/platforms/），遵循 PEP 8
- Shell 脚本必须使用 `set -xe`
- **Product/Variant 支持**：lunch target 格式为 `<board>-<product>-<variant>`，支持 debug/release 变体和多产品配置
- 每个任务不超过 2 小时工作量
