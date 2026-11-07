"""scanner 窗口机制单测（T11~T14）— 验证 state 推进 / 悬空缺口 / 防轰炸 / 无新K线跳过。

不触网：MockClient 鸭子类型注入 _process_symbol。
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from fixtures import MockClient, bull_fvg_sequence, candle_to_raw, make_candle, make_box

from ict_scanner.config import AppConfig
from ict_scanner.models import Direction, EventType
from ict_scanner.scanner import _process_symbol
from ict_scanner.state import ScanState

SYMBOL = "TESTUSDT"


def _config() -> AppConfig:
    return AppConfig(
        symbols=[SYMBOL],
        timeframe="15m",
        kline_limit_cold=1500,
        max_boxes=3,
        displacement_ratio=0.6,
    )


class TestScannerWindow(unittest.TestCase):
    # ------------------------------------------------------------------
    # T11 热启动推进：第二轮窗口 3 根（1 新 + 2 参考），无重复 FORMATION
    # ------------------------------------------------------------------
    def test_t11_hot_start_window_advance_no_duplicates(self):
        seq = bull_fvg_sequence()  # k0..k3
        # 第一轮：冷启动处理到 k3（FVG 在 k2 形成但不推送——防轰炸）
        c1 = MockClient([[candle_to_raw(c) for c in seq]])
        state = ScanState()
        out1 = _process_symbol(SYMBOL, _config(), c1, state)

        self.assertIsNotNone(out1)
        self.assertEqual(out1.events, [], "冷启动不得推送历史事件（防轰炸）")
        self.assertEqual(len(out1.boxes), 1, "state 必须初始化为活跃盒子")

        # 模拟 run_scan 落盘：冷启动结果写入 state
        state.set(SYMBOL, out1.last_open, out1.boxes)

        # 第二轮：k4 新收盘（不触及盒子：low=104.2 > top=104）
        k4 = make_candle(4, o=104.6, h=105, l=104.2, c=104.8)
        c2 = MockClient([
            [candle_to_raw(c) for c in seq[3:] + [k4]],     # probe 2 根: k3,k4
            [candle_to_raw(c) for c in seq[2:] + [k4]],     # 窗口 3 根: k2,k3,k4
        ])
        out2 = _process_symbol(SYMBOL, _config(), c2, state)

        self.assertIsNotNone(out2)
        self.assertEqual(out2.events, [], "窗口重算不得重复推送上一窗口的 FORMATION")
        self.assertEqual(len(out2.boxes), 1, "悬空盒子必须延续到 state")
        self.assertEqual(out2.last_open, k4.open_time, "state 时间戳必须推进")
        # 拉取根数：probe=2，窗口=3
        self.assertEqual([call["limit"] for call in c2.calls], [2, 3])

    # ------------------------------------------------------------------
    # T12 悬空缺口触及：state 中的窗口外盒子被新 K 线回补 → MITIGATION
    # ------------------------------------------------------------------
    def test_t12_dangling_box_mitigated(self):
        seq = bull_fvg_sequence()
        dangling = make_box(Direction.BULL, bottom=101, top=104, formed_at_index=2)

        state = ScanState()
        state.set(SYMBOL, seq[3].open_time, [dangling])

        # k4 大跌触及 bottom=101
        k4 = make_candle(4, o=103, h=103.5, l=100, c=100.5)
        c = MockClient([
            [candle_to_raw(x) for x in seq[3:] + [k4]],     # probe 2 根: k3,k4
            [candle_to_raw(x) for x in seq[2:] + [k4]],     # 窗口 3 根: k2,k3,k4
        ])
        out = _process_symbol(SYMBOL, _config(), c, state)

        self.assertEqual(len(out.events), 1)
        self.assertIs(out.events[0].event_type, EventType.MITIGATION)
        self.assertEqual(out.events[0].box, dangling)
        self.assertEqual(out.boxes, [], "回补后盒子必须从 state 移除")

    # ------------------------------------------------------------------
    # T13 无新已收盘 K 线：返回 None 跳过（重复 cron 场景）
    # ------------------------------------------------------------------
    def test_t13_no_new_closed_candle_skips(self):
        seq = bull_fvg_sequence()
        state = ScanState()
        state.set(SYMBOL, seq[3].open_time, [])

        c = MockClient([[candle_to_raw(c) for c in seq[2:]]])
        out = _process_symbol(SYMBOL, _config(), c, state)
        self.assertIsNone(out)

    # ------------------------------------------------------------------
    # T14 冷启动只推最新一根上的事件：最新 K 线形成 FVG 则推送
    # ------------------------------------------------------------------
    def test_t14_cold_start_pushes_only_latest_candle_events(self):
        # 专用序列：k0..k3，其中 k2/k3 各形成一个 bull FVG
        k0 = make_candle(0, o=100, h=101, l=99, c=100.5)
        k1 = make_candle(1, o=100.5, h=106, l=100, c=105.5)  # 阳线 body=5 range=6 → 5 > 3.6 ✓
        k2 = make_candle(2, o=105.5, h=108, l=105, c=107.5)  # 阳线 body=2 range=3 → 2 > 1.8 ✓
        k3 = make_candle(3, o=109, h=112, l=109, c=111.5)    # c0: low=109 > k1.high=106 ✓
        # k3 判定: c1=k2 阳线 body=2 range=3 → is_disp ✓；c0.low=109 > c2.high(k1)=106 ✓
        # → FVG#2 在 k3 形成 (bottom=106, top=109)
        # k2 判定: c1=k1 阳线 is_disp ✓；c0.low=105 > c2.high(k0)=101 ✓
        # → FVG#1 在 k2 形成 (bottom=101, top=105)
        # k3 是否回补 FVG#1？low=109 > top=105 ✓ 否

        c = MockClient([[candle_to_raw(x) for x in [k0, k1, k2, k3]]])
        state = ScanState()
        out = _process_symbol(SYMBOL, _config(), c, state)

        self.assertEqual(len(out.events), 1, "冷启动只推最新一根 K 线的事件")
        self.assertIs(out.events[0].event_type, EventType.FORMATION)
        self.assertEqual((out.events[0].box.bottom, out.events[0].box.top), (106.0, 109.0))
        self.assertEqual(out.events[0].candle_open_time, k3.open_time)
        # state 初始化：两个盒子（FVG#1 老在前，FVG#2 新在后）
        self.assertEqual(len(out.boxes), 2)
        self.assertEqual((out.boxes[0].bottom, out.boxes[0].top), (101.0, 105.0))


if __name__ == "__main__":
    unittest.main()
