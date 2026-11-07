"""测试夹具：K 线 / 盒子构造辅助。

时间戳从 1_000_000_000_000 起，每根 +15 分钟（900_000 ms），与生产周期一致。
价格用简单十进制值，人工可验证。
"""

from __future__ import annotations

from ict_scanner.models import Box, Candle, Direction

BASE_TIME = 1_000_000_000_000
STEP_MS = 900_000  # 15 分钟


def make_candle(index: int, o: float, h: float, l: float, c: float) -> Candle:
    """按序号构造 K 线：index 0 为窗口第一根，open_time 随序号递增。"""
    assert h >= max(o, c) and l <= min(o, c), f"K 线 #{index} 非法: OHLC={o},{h},{l},{c}"
    assert h >= l
    return Candle(
        open_time=BASE_TIME + index * STEP_MS,
        open=o,
        high=h,
        low=l,
        close=c,
        volume=1.0,
        close_time=BASE_TIME + index * STEP_MS + STEP_MS - 1,
    )


def make_box(
    direction: Direction,
    bottom: float,
    top: float,
    formed_at_index: int = 0,
) -> Box:
    """构造注入用盒子（formed_at_open_time 按 index 换算）。"""
    return Box(
        direction=direction,
        bottom=bottom,
        top=top,
        formed_at_open_time=BASE_TIME + formed_at_index * STEP_MS,
    )


def candle_to_raw(c: Candle) -> list:
    """Candle → 币安 klines REST 数组格式（scanner/_closed_candles 解析用）。"""
    return [c.open_time, c.open, c.high, c.low, c.close, c.volume, c.close_time]


def bull_fvg_sequence() -> list[Candle]:
    """标准 bull FVG 场景 k0..k2：形成盒子 (bottom=101, top=104)。

    k3 为后续无关 K 线（非位移、不填补），供窗口推进用例续接。
    """
    return [
        make_candle(0, o=100, h=101, l=99, c=100.5),
        make_candle(1, o=100.5, h=104, l=100, c=103.5),
        make_candle(2, o=104, h=105, l=104, c=104.5),
        make_candle(3, o=104.5, h=104.8, l=104.2, c=104.6),
    ]


class MockClient:
    """鸭子类型替代 BinanceClient：按调用顺序返回预置 klines，记录调用参数。"""

    def __init__(self, responses: list[list[list]]):
        self._responses = responses
        self.calls: list[dict] = []

    def get_klines(self, symbol: str, interval: str, limit: int, end_time=None) -> list[list]:
        self.calls.append({"symbol": symbol, "interval": interval, "limit": limit})
        idx = len(self.calls) - 1
        if idx >= len(self._responses):
            raise AssertionError("MockClient 响应队列耗尽")
        return self._responses[idx]
