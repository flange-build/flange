"""配置注册表 — 管理平台/SoC/板级配置的注册、合并与查询"""

load("//build:deep_merge.bzl", "deep_merge")
load("//platform/rockchip:config.bzl", "ROCKCHIP_PLATFORM")
load("//platform/rockchip/rk3566:config.bzl", "RK3566_SOC")
load("//board/radxa-zero3w:board.bzl", "RADXA_ZERO3W_BOARD")
load("//board/neons-core3566-nanob:board.bzl", "NEONS_CORE3566_NANOB_BOARD")

_PLATFORMS = {
    "rockchip": ROCKCHIP_PLATFORM,
}

_SOCS = {
    "rk3566": RK3566_SOC,
}

_BOARDS = {
    "radxa-zero3w": RADXA_ZERO3W_BOARD,
    "neons-core3566-nanob": NEONS_CORE3566_NANOB_BOARD,
}

REGISTERED_BOARDS = _BOARDS.keys()

def get_board_config(board_name):
    """返回经过三层合并（platform → SoC → board）的完整配置 dict。

    Args:
        board_name: 已注册的板子名称

    Returns:
        合并后的配置 dict
    """
    if board_name not in _BOARDS:
        fail("板子 \"{}\" 未注册，已注册的板子: {}".format(
            board_name,
            ", ".join(REGISTERED_BOARDS),
        ))

    board = _BOARDS[board_name]
    soc_name = board["soc"]
    platform_name = board["platform"]

    if soc_name not in _SOCS:
        fail("SoC \"{}\" 未注册".format(soc_name))
    if platform_name not in _PLATFORMS:
        fail("平台 \"{}\" 未注册".format(platform_name))

    platform_config = _PLATFORMS[platform_name]
    soc_config = _SOCS[soc_name]

    return deep_merge(deep_merge(platform_config, soc_config), board)
