## 1. 目标树与配置摘要（纯数据，可独立测试）

- [x] 1.1 `builder/config/query.py` 增加 `build_target_tree()`：从 `discover_boards()`
      构造 平台 → SoC → 板 → product → variant 的树，不触发 jsonnet 求值
- [x] 1.2 增加 `summarize_config(board, product, variant)`：把求值结果整理成
      分节的 (标题, [(键, 值)]) 表，供 TUI 与非 TUI 场景共用
- [x] 1.3 树与摘要的单元测试：层级完整性、与 `get_valid_targets()` 的叶子对账

## 2. TUI

- [x] 2.1 `builder/lunch_tui.py`：curses 双栏骨架、树的展开/折叠/导航
- [x] 2.2 右栏渲染：非叶节点显示子项统计，叶节点显示配置表
- [x] 2.3 配置表后台线程加载 + 缓存 + 加载中占位
- [x] 2.4 打开时定位到当前目标；按名字过滤
- [x] 2.5 选中写出目标到 `--out` 文件；取消不写

## 3. 接入 envsetup

- [x] 3.1 `lunch` 无参数且是 TTY 时走 TUI，读回选择并复用既有的导出与保存路径
- [x] 3.2 非 TTY 或 `--no-tui` 回退原编号列表
- [x] 3.3 `lunch --help` 说明新交互

## 4. 验证

- [x] 4.1 TUI 纯逻辑（树、过滤、光标、选择）的单元测试，不依赖终端
- [x] 4.2 结构性测试：非 TTY 回退路径存在
- [x] 4.3 全量测试 + `openspec validate --all --strict`

- [ ] 4.4 由使用者在真实终端确认交互手感（PTY 只能验证渲染与按键路径，
      "顺不顺手"机器判断不了）—— 确认后归档本变更
