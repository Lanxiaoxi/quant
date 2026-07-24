"""策略代码加载：exec 用户代码 → 找到 Strategy 子类。

安全说明（DESIGN.md 4.6）：单人使用场景，exec 在独立子进程内进行，
不做 import 白名单硬限制；策略代码无网络代理环境变量，降低误用风险。
"""
from __future__ import annotations

import inspect
from typing import Type

from app.engine.strategy import Strategy


def load_strategy_class(code: str) -> Type[Strategy]:
    """exec 策略代码，返回其中定义的 Strategy 子类（取最后一个）。"""
    namespace: dict = {"__name__": "user_strategy"}
    exec(compile(code, "<strategy>", "exec"), namespace)  # noqa: S102 - 单人信任模型
    classes = [v for v in namespace.values()
               if inspect.isclass(v) and issubclass(v, Strategy) and v is not Strategy]
    if not classes:
        raise ValueError("代码中未找到 Strategy 子类")
    return classes[-1]
