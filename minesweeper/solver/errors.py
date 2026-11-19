"""求解器层的公共异常。"""


class SolverError(RuntimeError):
    """自动计算过程中的可预期错误（不满足前置条件、窗口为空等）。"""
