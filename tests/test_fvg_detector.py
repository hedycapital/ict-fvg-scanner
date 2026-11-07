"""fvg_detector 单测 T1~T10 — 覆盖 Pine 语义全部边界。

运行: python -m unittest discover tests -v
"""

from __future__ import annotations

import unittest

from fixtures import make_box, make_candle

from ict_scanner.fvg_detector import detect_fvg_events
from ict_scanner.models import Direction, EventType


def _types(events):
    return [e.event_type for e in events]


class TestFvgDetector(unittest.TestCase):
    # ------------------------------------------------------------------
    # T1 标准 bull 形态：三根 K 线形成向上缺口
    # ------------------------------------------------------------------
    def test_t1_bull_formation_standard(self):
        c2 = make_candle(0, o=100, h=101, l=99, c=100.5)
        c1 = make_candle(1, o=100.5, h=104, l=100, c=103.5)   # 阳线 body=3 range=4 → 3 > 2.4 ✓
        c0 = make_candle(2, o=104, h=105, l=104, c=104.5)     # low=104 > c2.high=101 ✓

        r = detect_fvg_events([c2, c1, c0])

        self.assertEqual(_types(r.events), [EventType.FORMATION])
        box = r.events[0].box
        self.assertIs(box.direction, Direction.BULL)
        self.assertEqual((box.bottom, box.top), (101.0, 104.0))
        self.assertEqual(r.events[0].candle_open_time, c0.open_time)
        # 活跃盒子快照：老→新，恰含该盒子
        self.assertEqual(len(r.boxes), 1)
        self.assertEqual(r.boxes[0], box)

    # ------------------------------------------------------------------
    # T2 标准 bear 形态
    # ------------------------------------------------------------------
    def test_t2_bear_formation_standard(self):
        c2 = make_candle(0, o=100, h=101, l=99, c=99.5)
        c1 = make_candle(1, o=99.5, h=100, l=96, c=96.5)      # 阴线 body=3 range=4 ✓
        c0 = make_candle(2, o=96.5, h=96.5, l=95, c=95.5)     # high=96.5 < c2.low=99 ✓

        r = detect_fvg_events([c2, c1, c0])

        self.assertEqual(_types(r.events), [EventType.FORMATION])
        box = r.events[0].box
        self.assertIs(box.direction, Direction.BEAR)
        self.assertEqual((box.bottom, box.top), (96.5, 99.0))

    # ------------------------------------------------------------------
    # T3 位移过滤严格大于：body/range 恰好 0.6 不通过，0.62 通过
    # ------------------------------------------------------------------
    def test_t3_displacement_strict_greater(self):
        c2 = make_candle(0, o=100, h=101, l=99, c=100.5)

        # body=3, range=5 → 3 > 5*0.6(=3.0) 为 False → 不形成
        c1_eq = make_candle(1, o=100, h=105, l=100, c=103)
        c0_eq = make_candle(2, o=104, h=105, l=104, c=104.5)
        r = detect_fvg_events([c2, c1_eq, c0_eq])
        self.assertEqual(r.events, [], "body/range 恰好等于 0.6 必须不形成")

        # body=3.1 → 3.1 > 3.0 ✓ → 形成
        c1_gt = make_candle(1, o=100, h=105, l=100, c=103.1)
        c0_gt = make_candle(2, o=104, h=105, l=104, c=104.5)
        r = detect_fvg_events([c2, c1_gt, c0_gt])
        self.assertEqual(_types(r.events), [EventType.FORMATION])

    # ------------------------------------------------------------------
    # T4 创建等号边界：c0.low == c2.high 不形成（严格大于）
    # ------------------------------------------------------------------
    def test_t4_creation_equality_not_formed(self):
        c2 = make_candle(0, o=100, h=101, l=99, c=100.5)
        c1 = make_candle(1, o=100.5, h=104, l=100, c=103.5)
        c0 = make_candle(2, o=101, h=103, l=101, c=102.5)     # low=101 == c2.high

        r = detect_fvg_events([c2, c1, c0])
        self.assertEqual(r.events, [])
        self.assertEqual(r.boxes, [])

    # ------------------------------------------------------------------
    # T5 填补等号边界：c0.low == box.bottom 触发 MITIGATION（<=）
    # ------------------------------------------------------------------
    def test_t5_mitigation_equality_triggers(self):
        # 前三根形成 bull 盒子 (bottom=101, top=104)
        seq = [
            make_candle(0, o=100, h=101, l=99, c=100.5),
            make_candle(1, o=100.5, h=104, l=100, c=103.5),
            make_candle(2, o=104, h=105, l=104, c=104.5),
        ]
        # 第 4 根 low 恰好等于 bottom；其 c1 引用（#2）body=0.5 range=1 → 非位移，不新建
        c3 = make_candle(3, o=103, h=103.5, l=101, c=101.5)

        r = detect_fvg_events(seq + [c3])
        self.assertEqual(_types(r.events), [EventType.FORMATION, EventType.MITIGATION])
        self.assertEqual(r.events[1].candle_open_time, c3.open_time)
        self.assertEqual(r.boxes, [], "触及即回补删除")

    # ------------------------------------------------------------------
    # T6 一根 K 线填补多个盒子：倒序遍历，事件序 新→老
    # ------------------------------------------------------------------
    def test_t6_multi_mitigation_reverse_order(self):
        seq = [
            # 形成盒1 (101, 104)
            make_candle(0, o=100, h=101, l=99, c=100.5),
            make_candle(1, o=100.5, h=104, l=100, c=103.5),
            make_candle(2, o=104, h=105, l=104, c=104.5),
            # 形成盒2 (104.8, 106.8)；c0.low=106.8 未触及盒1
            make_candle(3, o=104, h=104.8, l=103.8, c=104.4),
            make_candle(4, o=104.4, h=107, l=104, c=106.5),
            make_candle(5, o=106.8, h=108, l=106.8, c=107.5),
            # 形成盒3 (107.5, 109.8)；c0.low=109.8 未触及盒1/盒2
            make_candle(6, o=107, h=107.5, l=106.5, c=107.2),
            make_candle(7, o=107.2, h=110, l=107, c=109.5),
            make_candle(8, o=109.8, h=111, l=109.8, c=110),
        ]
        # 大 K 线 low=100 同时触及三个盒子；其 c1 引用（#8）非位移不新建
        big = make_candle(9, o=110, h=110.5, l=100, c=100.5)

        r = detect_fvg_events(seq + [big])

        self.assertEqual(_types(r.events), [EventType.FORMATION] * 3 + [EventType.MITIGATION] * 3)
        mits = r.events[3:]
        # 倒序遍历：数组 [盒1,盒2,盒3]（老→新）→ 从 i=2 开始 → 事件序 盒3, 盒2, 盒1
        self.assertEqual(
            [(m.box.bottom, m.box.top) for m in mits],
            [(107.5, 109.8), (104.8, 106.8), (101.0, 104.0)],
            "填补事件必须 新→老 顺序（Pine 倒序遍历语义）",
        )
        self.assertEqual(r.boxes, [])
        self.assertTrue(all(m.candle_open_time == big.open_time for m in mits))

    # ------------------------------------------------------------------
    # T7 挤出：第 4 个盒子 push 后最老的被 EVICTED（不推送但入事件日志）
    # ------------------------------------------------------------------
    def test_t7_eviction_fifo(self):
        seq = [
            # 盒1 (101, 104)
            make_candle(0, o=100, h=101, l=99, c=100.5),
            make_candle(1, o=100.5, h=104, l=100, c=103.5),
            make_candle(2, o=104, h=105, l=104, c=104.5),
            # 盒2 (104.8, 106.8)
            make_candle(3, o=104, h=104.8, l=103.8, c=104.4),
            make_candle(4, o=104.4, h=107, l=104, c=106.5),
            make_candle(5, o=106.8, h=108, l=106.8, c=107.5),
            # 盒3 (107.5, 109.8)
            make_candle(6, o=107, h=107.5, l=106.5, c=107.2),
            make_candle(7, o=107.2, h=110, l=107, c=109.5),
            make_candle(8, o=109.8, h=111, l=109.8, c=110),
            # 盒4 (110.8, 112.8) → push 后 len=4 > 3 → 盒1 EVICTED
            make_candle(9, o=110, h=110.8, l=109.9, c=110.4),
            make_candle(10, o=110.4, h=113, l=110, c=112.5),
            make_candle(11, o=112.8, h=114, l=112.8, c=113),
        ]

        r = detect_fvg_events(seq)

        self.assertEqual(_types(r.events),
                         [EventType.FORMATION] * 4 + [EventType.EVICTED])
        evicted = r.events[-1].box
        self.assertEqual((evicted.bottom, evicted.top), (101.0, 104.0), "先进先出：挤出最老的盒1")
        # 同根事件序：FORMATION(box4) 在前，EVICTED(box1) 在后（push → 检查容量）
        self.assertEqual(r.events[-2].box.top, 112.8)
        self.assertEqual(r.events[-1].candle_open_time, seq[-1].open_time)
        # 活跃盒子：[盒2, 盒3, 盒4] 老→新
        self.assertEqual([(b.bottom, b.top) for b in r.boxes],
                         [(104.8, 106.8), (107.5, 109.8), (110.8, 112.8)])

    # ------------------------------------------------------------------
    # T8 状态恢复：注入悬空缺口，窗口第 1 根即触发 MITIGATION（关键修正①）
    # ------------------------------------------------------------------
    def test_t8_initial_boxes_dangling_gap_detected(self):
        # 悬空缺口：6 天前形成（远在窗口之外），从未回补
        dangling = make_box(Direction.BULL, bottom=50, top=52, formed_at_index=-100)
        # 窗口仅一根 K 线（i=0 无 [2] 引用，不判创建），但填补判定必须生效
        c0 = make_candle(0, o=103, h=103.5, l=49, c=49.5)

        r = detect_fvg_events([c0], initial_boxes=[dangling])

        self.assertEqual(_types(r.events), [EventType.MITIGATION],
                         "窗口外形成的悬空缺口被触及必须产生事件（防静默漏检）")
        self.assertEqual(r.events[0].box, dangling)
        self.assertEqual(r.events[0].candle_open_time, c0.open_time)
        self.assertEqual(r.boxes, [])

    # ------------------------------------------------------------------
    # T9 零震幅：c1 high == low → 安全跳过，无异常、不形成
    # ------------------------------------------------------------------
    def test_t9_zero_range_candle_safe(self):
        c2 = make_candle(0, o=100, h=101, l=99, c=100.5)
        c1 = make_candle(1, o=100.5, h=100.5, l=100.5, c=100.5)  # 零震幅
        c0 = make_candle(2, o=102, h=104, l=102, c=103.5)        # low=102 越过 c2.high=101

        r = detect_fvg_events([c2, c1, c0])
        self.assertEqual(r.events, [], "零震幅 K 线不得形成缺口（位移过滤必为 False）")
        self.assertEqual(r.boxes, [])

    # ------------------------------------------------------------------
    # T10 注入盒子去重：窗口内重新模拟出同 key 盒子不产生幽灵 FORMATION
    # ------------------------------------------------------------------
    def test_t10_injected_box_no_duplicate_formation(self):
        # 注入盒子 formed_at 恰为窗口第 3 根（异常 state 场景的防御）
        box = make_box(Direction.BULL, bottom=101, top=104, formed_at_index=2)
        seq = [
            make_candle(0, o=100, h=101, l=99, c=100.5),
            make_candle(1, o=100.5, h=104, l=100, c=103.5),
            make_candle(2, o=104, h=105, l=104, c=104.5),  # 会重新"形成"同 key 盒子
            make_candle(3, o=103, h=103.5, l=101, c=101.5),  # 触及填补
        ]

        r = detect_fvg_events(seq, initial_boxes=[box])

        self.assertEqual(_types(r.events), [EventType.MITIGATION],
                         "注入盒子的重复形成必须跳过，只保留触及事件")
        self.assertEqual(r.boxes, [])


if __name__ == "__main__":
    unittest.main()
