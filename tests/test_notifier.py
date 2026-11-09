"""notifier 单测（T15~T19）：EVICTED 过滤 / 4000 字符分片 / TV 图表链接 / 版式要素。"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fixtures import BASE_TIME, make_box

from ict_scanner.models import Direction, EventType, FvgEvent
from ict_scanner.notifier import TELEGRAM_LIMIT, build_blocks
from ict_scanner.scanner import SymbolOutcome


def _outcome(symbol: str, n_events: int, event_type=EventType.FORMATION) -> SymbolOutcome:
    events = [
        FvgEvent(
            event_type,
            make_box(Direction.BULL, bottom=100 + i, top=110 + i, formed_at_index=i),
            BASE_TIME + i * 900_000,
        )
        for i in range(n_events)
    ]
    return SymbolOutcome(symbol, events, BASE_TIME, events and [events[-1].box] or [])


class TestNotifier(unittest.TestCase):
    def test_t15_evicted_not_pushed(self):
        outcome = _outcome("xyz:BTC", 0)
        outcome.events = [
            FvgEvent(EventType.FORMATION, make_box(Direction.BULL, 100, 104), BASE_TIME),
            FvgEvent(EventType.EVICTED, make_box(Direction.BEAR, 90, 95), BASE_TIME),
        ]
        blocks = build_blocks([outcome])
        joined = "\n".join(blocks)
        self.assertIn("100–104", joined, "FORMATION 事件必须推送")
        self.assertNotIn("90–95", joined, "EVICTED 事件不得出现在推送内容中")

    def test_t20_layout_elements(self):
        """版式：分组事件数统计、动作词、方向色标、树状缩进、标题统计行。"""
        outcome = _outcome("xyz:TSLA", 2, EventType.MITIGATION)
        blocks = build_blocks([outcome])
        joined = "\n".join(blocks)
        self.assertIn(" · 2 事件", joined, "标的行必须带事件数统计")
        self.assertIn(" · 1 标的 · 2 事件", joined, "标题行必须带轮次统计")
        self.assertIn("<b>回补</b>", joined, "动作词必须加粗")
        self.assertIn("🟢BULL", joined, "BULL 必须带绿点色标")
        self.assertIn("├ 🎯", joined, "非末行事件必须用 ├ 缩进")
        self.assertIn("└ 🎯", joined, "末行事件必须用 └ 缩进")
        self.assertIn("<code>100–110</code>", joined, "价格区间必须等宽高亮")

    def test_t16_chunking_over_limit(self):
        # 30 个标的 × 30 事件 ≈ 远超 4000 字符 → 必然分片且每片 ≤ 上限
        outcomes = [_outcome(f"xyz:SYM{i}", 30) for i in range(30)]
        blocks = build_blocks(outcomes)
        self.assertGreater(len(blocks), 1, "超长内容必须分片")
        for b in blocks:
            self.assertLessEqual(len(b), TELEGRAM_LIMIT)

    # ------------------------------------------------------------------
    # T19 TV 图表链接：xyz:TSLA → HIP3XYZ:TSLAUSDC.P，且链接可点击
    # ------------------------------------------------------------------
    def test_t19_tradingview_chart_link(self):
        from ict_scanner.notifier import tv_chart_symbol, tv_chart_url

        self.assertEqual(tv_chart_symbol("xyz:TSLA"), "HIP3XYZ:TSLAUSDC.P")
        self.assertEqual(tv_chart_symbol("xyz:GOLD"), "HIP3XYZ:GOLDUSDC.P")

        outcome = _outcome("xyz:TSLA", 1)
        blocks = build_blocks([outcome])
        joined = "\n".join(blocks)
        self.assertIn(
            "https://www.tradingview.com/chart/?symbol=HIP3XYZ%3ATSLAUSDC.P",
            joined,
            "推送必须包含可点击的 TV 图表链接",
        )
        self.assertIn(">TSLA</a>", joined, "链接显示名应为去除 dex 前缀的资产名")


if __name__ == "__main__":
    unittest.main()
