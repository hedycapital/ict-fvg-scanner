"""verify 子命令：TV 一致性人工比对工具。

输出三段内容，供用户在 TradingView `BINANCE:<SYMBOL>.P` 15m 图表上逐项核对：
  ① 最新 3 根已收盘 K 线 OHLC   —— 数据同源对齐
  ② 当前活跃缺口（老→新）      —— 对照 TV 图表上现存的 FVG 盒子
  ③ 近期事件日志                —— 对照 TV 上已消失（被回补/挤出）的盒子

用法: python -m ict_scanner verify --symbol BTCUSDT --limit 1500
"""

from __future__ import annotations

import argparse
import datetime as dt

from .binance_client import BinanceClient
from .fvg_detector import detect_fvg_events
from .models import Candle, Direction, EventType

_EVENT_LABEL = {
    EventType.FORMATION: "形成",
    EventType.MITIGATION: "回补",
    EventType.EVICTED: "挤出",
}
_DIR_LABEL = {Direction.BULL: "BULL↑", Direction.BEAR: "BEAR↓"}


def _fmt_ts(ms: int) -> str:
    t = dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc)
    return t.strftime("%m-%d %H:%M")


def _fmt_price(v: float) -> str:
    return f"{v:g}"


def run_verify(symbol: str, limit: int, interval: str) -> int:
    client = BinanceClient()
    raw = client.get_klines(symbol, interval, limit)
    now_ms = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    candles = [Candle.from_binance_kline(k) for k in raw]
    closed = [c for c in candles if c.close_time <= now_ms]

    print(f"═══ verify {symbol} {interval} ═══")
    print(f"拉取 {len(candles)} 根，已收盘 {len(closed)} 根（丢弃未收盘 {len(candles) - len(closed)} 根）")

    if len(closed) < 3:
        print("已收盘 K 线不足 3 根，无法检测")
        return 1

    result = detect_fvg_events(closed)

    # ── ① 最新 3 根已收盘 K 线 ──────────────────────────────────────────
    print("\n── ① 最新 3 根已收盘 K 线（对照 TV 当前 K 线 OHLC）──")
    for c in closed[-3:]:
        print(f"  {_fmt_ts(c.open_time)} UTC  O={_fmt_price(c.open)} H={_fmt_price(c.high)} "
              f"L={_fmt_price(c.low)} C={_fmt_price(c.close)}")

    # ── ② 活跃缺口（老→新）─────────────────────────────────────────────
    print(f"\n── ② 活跃缺口 {len(result.boxes)} 个（老→新，对照 TV 现存 FVG 盒子）──")
    if not result.boxes:
        print("  （无）")
    for b in result.boxes:
        print(f"  {_DIR_LABEL[b.direction]}  bottom={_fmt_price(b.bottom)}  top={_fmt_price(b.top)}"
              f"  形成于 {_fmt_ts(b.formed_at_open_time)} UTC")

    # ── ③ 近期事件（最新 30 条）────────────────────────────────────────
    print(f"\n── ③ 事件日志（共 {len(result.events)} 条，显示最新 30 条）──")
    for ev in result.events[-30:]:
        b = ev.box
        print(f"  [{_EVENT_LABEL[ev.event_type]:>2}] {_DIR_LABEL[b.direction]} "
              f"[{_fmt_price(b.bottom)}, {_fmt_price(b.top)}]"
              f"  盒子形成 {_fmt_ts(b.formed_at_open_time)} / 事件 {_fmt_ts(ev.candle_open_time)} UTC")

    print("\n比对提示：TV 图表时区若非 UTC，请将上述时间 +8h 对照北京时间（或把 TV 时区切到 UTC）。")
    return 0


def build_verify_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--symbol", default="BTCUSDT", help="标的，如 BTCUSDT")
    parser.add_argument("--limit", type=int, default=1500, help="拉取 K 线根数（默认 1500 ≈ 15.6 天）")
    parser.add_argument("--interval", default="15m", help="K 线周期（默认 15m）")
    return parser
