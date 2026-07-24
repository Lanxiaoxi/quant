"""tushare Pro 客户端：token 鉴权 + 按分钟节流 + 限流退避重试。

设计约定（DESIGN.md 5.1）：
- 同步策略以"按 trade_date 拉全市场快照"为主，调用次数极低；
- 限流异常（每分钟 N 次）做指数退避，最多重试 4 次；
- 返回空 DataFrame 表示无数据，不抛异常。
"""
from __future__ import annotations

import logging
import time
from typing import Any

import pandas as pd
import tushare as ts

from app.core.config import settings

log = logging.getLogger(__name__)

_RATE_LIMIT_HINTS = ("每分钟", "频次", "频率", "limit", "exceeded")


class TushareClient:
    def __init__(self, token: str | None = None, max_calls_per_minute: int | None = None):
        self._token = token or settings.tushare_token
        if not self._token:
            raise RuntimeError("未配置 TUSHARE_TOKEN，请在 backend/.env 中填写后重试")
        self._pro = ts.pro_api(self._token)
        rpm = max_calls_per_minute or settings.tushare_max_calls_per_minute
        self._min_interval = 60.0 / rpm
        self._last_call_at = 0.0

    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last_call_at)
        if wait > 0:
            time.sleep(wait)
        self._last_call_at = time.monotonic()

    @staticmethod
    def _is_rate_limit(exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(h in msg for h in _RATE_LIMIT_HINTS)

    def query(self, api_name: str, fields: str | None = None, max_retries: int = 4, **params: Any) -> pd.DataFrame:
        """调用 tushare 接口并返回 DataFrame；限流时指数退避重试。"""
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            self._throttle()
            try:
                df: pd.DataFrame | None = (
                    self._pro.query(api_name, fields=fields, **params)
                    if fields
                    else self._pro.query(api_name, **params)
                )
                return df if df is not None else pd.DataFrame()
            except Exception as exc:  # noqa: BLE001 - tushare 异常类型不统一
                last_exc = exc
                if self._is_rate_limit(exc) and attempt < max_retries:
                    backoff = min(2**attempt * 5, 60)
                    log.warning("tushare %s 限流，%ds 后第 %d 次重试", api_name, backoff, attempt + 1)
                    time.sleep(backoff)
                    continue
                raise RuntimeError(f"tushare 接口 {api_name} 调用失败: {exc}") from exc
        raise RuntimeError(f"tushare 接口 {api_name} 重试耗尽: {last_exc}")
