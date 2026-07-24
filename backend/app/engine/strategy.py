"""策略基类与 Param 声明式参数（DESIGN.md 4.1 / 4.4）。

- Param 描述符：声明默认值与取值范围，引擎据此生成参数表单 JSON Schema，后期直接用于参数寻优；
- Strategy：用户策略继承本类，实现 setup / on_bar（以及可选的 schedule 回调函数）。
"""
from __future__ import annotations

from typing import Any


class Param:
    """声明式策略参数。

    用法：
        class DualMA(Strategy):
            fast = Param(default=5, min=2, max=60, step=1, label="快线周期")
    """

    def __init__(self, default: Any, min: float | None = None, max: float | None = None,
                 step: float | None = None, label: str = ""):
        self.default = default
        self.min = min
        self.max = max
        self.step = step
        self.label = label
        self.name: str = ""  # 由 __set_name__ 注入

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def __get__(self, obj: "Strategy | None", objtype: type | None = None) -> Any:
        if obj is None:
            return self
        return obj._param_values.get(self.name, self.default)

    def __set__(self, obj: "Strategy", value: Any) -> None:
        obj._param_values[self.name] = value

    def validate(self, value: Any) -> Any:
        """范围校验（寻优/表单提交时调用）。"""
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if self.min is not None and value < self.min:
                raise ValueError(f"参数 {self.name}={value} 小于下限 {self.min}")
            if self.max is not None and value > self.max:
                raise ValueError(f"参数 {self.name}={value} 大于上限 {self.max}")
        return value


class Strategy:
    """策略基类。生命周期：setup(ctx) 一次 → on_bar(ctx) 每根 bar 一次。"""

    def __init__(self, **param_overrides: Any):
        self._param_values: dict[str, Any] = {}
        for name, param in self.params_schema().items():
            if name in param_overrides:
                self._param_values[name] = param.validate(param_overrides[name])

    # ---- 用户实现 ----

    def setup(self, ctx) -> None:  # noqa: ANN001 - ctx 类型在 context.py，避免循环导入
        """回测/模拟启动时调用一次：设置 ctx.universe、ctx.benchmark、ctx.schedule 等。"""

    def on_bar(self, ctx) -> None:  # noqa: ANN001
        """每根 bar 调用一次：策略主逻辑。"""

    # ---- 参数反射 ----

    @classmethod
    def params_schema(cls) -> dict[str, Param]:
        """收集 MRO 上全部 Param（子类覆盖同名参数时以子类为准）。"""
        schema: dict[str, Param] = {}
        for klass in reversed(cls.__mro__):
            for key, value in vars(klass).items():
                if isinstance(value, Param):
                    value.name = key
                    schema[key] = value
        return schema

    @classmethod
    def params_json_schema(cls) -> list[dict[str, Any]]:
        """供前端自动生成参数表单（DESIGN.md 4.4）。"""
        return [
            {
                "name": name,
                "default": p.default,
                "min": p.min,
                "max": p.max,
                "step": p.step,
                "label": p.label or name,
            }
            for name, p in cls.params_schema().items()
        ]
