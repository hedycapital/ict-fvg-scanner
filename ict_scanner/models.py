"""核心数据模型（无 I/O）。

所有价格字段用 float：与 Pine Script / 币安 API 同为 IEEE double 语义，
严格保证判定行为与 TradingView 一致（不引入 Decimal）。
所有时间字段为毫秒级 Unix UTC 时间戳（与币安 K 线字段一致）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Direction(str, Enum):
    """缺口方向：bull = 向上缺口（价格下方真空区），bear = 向下缺口。"""

    BULL = "BULL"
    BEAR = "BEAR"


class EventType(str, Enum):
    """缺口生命周期事件。

    FORMATION  新缺口形成并被推入盒子数组 → 推送
    MITIGATION 价格触及已有缺口（视为回补）→ 推送
    EVICTED    数组超容量被挤出（max_boxes=3 先进先出）→ 不推送
    """

    FORMATION = "FORMATION"
    MITIGATION = "MITIGATION"
    EVICTED = "EVICTED"


@dataclass(frozen=True, slots=True)
class Candle:
    """一根 K 线（币安 /fapi klines 字段子集，够用即可 - YAGNI）。"""

    open_time: int    # 开盘时间 ms UTC
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int   # 收盘时间 ms UTC（用于已收盘判定）

    @classmethod
    def from_binance_kline(cls, k: list) -> Candle:
        """从币安 klines REST 数组构造：[open_time, open, high, low, close, volume, close_time, ...]"""
        return cls(
            open_time=int(k[0]),
            open=float(k[1]),
            high=float(k[2]),
            low=float(k[3]),
            close=float(k[4]),
            volume=float(k[5]),
            close_time=int(k[6]),
        )

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return self.high - self.low


@dataclass(slots=True)
class Box:
    """一个活跃 FVG 缺口盒子。

    唯一标识 = (direction, formed_at_open_time)：
    formed_at_open_time 是形成该缺口的第 3 根 K 线（Pine 中当前 K 线）的 open_time，
    state 恢复与重算去重均依赖此字段。
    """

    direction: Direction
    bottom: float
    top: float
    formed_at_open_time: int  # 形成时那根 K 线的 open_time ms

    def overlaps_candle(self, candle: Candle) -> bool:
        """填补判定（Pine 语义，触及即回补删除）：
        bull  缺口位于价格下方，candle.low  <= bottom 即触及；
        bear  缺口位于价格上方，candle.high >= top    即触及。
        """
        if self.direction is Direction.BULL:
            return candle.low <= self.bottom
        return candle.high >= self.top


@dataclass(frozen=True, slots=True)
class FvgEvent:
    """一次缺口事件，关联事件发生所在 K 线（用于窗口过滤）。"""

    event_type: EventType
    box: Box
    candle_open_time: int  # 事件发生的 K 线 open_time ms


@dataclass(slots=True)
class DetectionResult:
    """对一段 K 线窗口执行完整检测后的结果。"""

    events: list[FvgEvent] = field(default_factory=list)   # 按时间序（含 EVICTED）
    boxes: list[Box] = field(default_factory=list)         # 活跃盒子快照：老→新（Pine 数组原始顺序，push 尾部 / pop(0) 挤出）
