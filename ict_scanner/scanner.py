"""扫描编排：窗口计算 → 并发拉数 → 检测 → 过滤 → 推送 → 落盘。

窗口机制（宁重勿漏）：
  - 热启动：处理 open_time > state.last_candle_open_utc 的全部已收盘 K 线
    （cron 延迟/漏跑时窗口自动变宽，下轮补齐）；
  - 冷启动：全量重算但只推最新一根 K 线上的事件（防历史轰炸），
    state 以全量结果初始化，之后每轮自愈累积。

时序铁律：先推送后落盘——推送失败抛异常 → main 非零退出 → 不写 state →
下轮窗口含本轮 K 线自动重推。
"""

from __future__ import annotations

import datetime as dt
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from .config import AppConfig, load_config
from .fvg_detector import detect_fvg_events
from .hyperliquid_client import HyperliquidClient, HyperliquidError
from .models import INTERVAL_MS, PUSHABLE_EVENT_TYPES, Box, Candle, FvgEvent
from .state import ScanState, load_state, save_state
from .symbols import resolve_symbols

MAX_WORKERS = 4        # 并发拉取线程（HL candleSnapshot 权重较高，礼貌值防 429）


@dataclass(slots=True)
class SymbolOutcome:
    """单标的处理结果：待推送事件 + 推送成功后应写入 state 的新值。"""

    symbol: str
    events: list[FvgEvent]
    last_open: int      # 本轮最后处理的已收盘 K 线 open_time
    boxes: list[Box]    # 检测结束时活跃盒子（老→新）


def _closed_candles(raw: list[dict], now_ms: int) -> list[Candle]:
    """只保留已收盘 K 线。

    HL candleSnapshot 无 close_time 字段，由开盘时间 + 周期推导：
    t + INTERVAL_MS <= now 即已收盘（不依赖本地时钟猜周期，语义与币安版一致）。
    """
    return [Candle.from_hyperliquid(k) for k in raw if int(k["t"]) + INTERVAL_MS <= now_ms]


def _process_symbol(
    symbol: str,
    config: AppConfig,
    client: HyperliquidClient,
    state: ScanState,
) -> SymbolOutcome | None:
    """处理单标的。返回 None 表示无新已收盘 K 线（本轮跳过）。"""
    now_ms = int(time.time() * 1000)
    prev = state.get(symbol)

    if prev is None:
        # ── 冷启动 ────────────────────────────────────────────────────
        closed = _closed_candles(client.get_klines(symbol, config.timeframe, config.kline_limit_cold), now_ms)
        if len(closed) < 3:
            return None
        current_open = closed[-1].open_time
        result = detect_fvg_events(
            closed, None, config.max_boxes, config.displacement_ratio
        )
        # 只推最新一根 K 线上的事件（防历史轰炸）
        pushable = [e for e in result.events if e.candle_open_time >= current_open]
        return SymbolOutcome(symbol, pushable, current_open, result.boxes)

    # ── 热启动 ────────────────────────────────────────────────────────
    prev_last_open, prev_boxes = prev
    probe = _closed_candles(client.get_klines(symbol, config.timeframe, 2), now_ms)
    if not probe or probe[-1].open_time <= prev_last_open:
        return None  # 无新已收盘 K 线

    current_open = probe[-1].open_time
    n_window = (current_open - prev_last_open) // INTERVAL_MS
    need = min(n_window + 2, config.kline_limit_cold)  # +2 根参考（c1/c2）
    closed = _closed_candles(client.get_klines(symbol, config.timeframe, need), now_ms)
    if len(closed) < 3:
        return None

    result = detect_fvg_events(
        closed, prev_boxes, config.max_boxes, config.displacement_ratio
    )
    pushable = [e for e in result.events if e.candle_open_time > prev_last_open]
    return SymbolOutcome(symbol, pushable, current_open, result.boxes)


def _fmt_ts(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%m-%d %H:%M")


def _print_outcomes(outcomes: list[SymbolOutcome]) -> None:
    """DRY_RUN 输出：窗口诊断 + 事件明细（非白名单事件标注不推送）。"""
    for o in outcomes:
        print(f"\n[{o.symbol}] 事件 {len(o.events)} 条，最后处理 K 线 {_fmt_ts(o.last_open)} UTC，"
              f"活跃盒子 {len(o.boxes)} 个")
        for ev in o.events:
            b = ev.box
            note = "" if ev.event_type in PUSHABLE_EVENT_TYPES else "（不推送）"
            print(f"  {ev.event_type.value:<10} {b.direction.value} "
                  f"[{b.bottom:g}, {b.top:g}] @ {_fmt_ts(ev.candle_open_time)} UTC{note}")


def run_scan() -> int:
    from .notifier import send_scan_report

    config = load_config()
    client = HyperliquidClient(api_url=config.hl_api_url)
    state = load_state(config.state_path)

    symbols = resolve_symbols(config, client)
    mode = "DRY_RUN" if config.dry_run else "LIVE"
    print(f"[scan] 模式={mode} 标的={len(symbols)} state内已有={state.symbol_count}个标的")

    outcomes: list[SymbolOutcome] = []
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(_process_symbol, s, config, client, state): s for s in symbols
        }
        for fut in as_completed(futures):
            sym = futures[fut]
            try:
                outcome = fut.result()
                if outcome is not None:
                    outcomes.append(outcome)
            except HyperliquidError as exc:
                # 单标的失败（下架/无数据等）：记录不中断，该标的 state 不推进 → 下轮自动补
                failures.append(f"{sym}: {exc}")

    # 计数口径与推送一致：只统计推送白名单内的事件（FORMATION 后台记录不触发消息）
    total_events = sum(
        len([e for e in o.events if e.event_type in PUSHABLE_EVENT_TYPES])
        for o in outcomes
    )
    print(f"[scan] 有新K线的标的={len(outcomes)} 可推送事件={total_events} 单标的失败={len(failures)}")
    for f in failures:
        print(f"[warn] {f}")

    if total_events > 0:
        if config.dry_run:
            _print_outcomes(outcomes)
        else:
            # 铁律：先推送。失败抛异常 → 非零退出 → 不落盘 → 下轮重推
            send_scan_report(config, outcomes)

    if not config.dry_run:
        for o in outcomes:
            state.set(o.symbol, o.last_open, o.boxes)
        save_state(config.state_path, state)
        print(f"[scan] state 已落盘: {config.state_path}")
    else:
        print("[scan] DRY_RUN: 未推送、未落盘")

    return 0
