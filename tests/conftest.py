"""pytest 全局配置。"""


def pytest_addoption(parser):
    """``--update-golden`` 用于重新固化 golden 快照。

    golden 测试锁的是"重构不该改变的行为"。真要改变行为时，用这个开关重新
    固化，并在提交信息里说明改了哪一步、为什么 —— 而不是让断言悄悄放宽。
    """
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="重新写入 golden 快照，而不是与之比对",
    )
