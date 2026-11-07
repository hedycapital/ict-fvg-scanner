"""纯函数回归测试（T17~T18）：确定性 + 无副作用。

保证 fvg_detector 相同输入永远产出相同输出（state 恢复 / 重算幂等的前提）。
"""

from __future__ import annotations

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from fixtures import bull_fvg_sequence, candle_to_raw, make_box, make_candle

from ict_scanner.fvg_detector import detect_fvg_events
from ict_scanner.models import Direction


class TestDetectorPurity(unittest.TestCase):
    def test_t17_deterministic_output(self):
        seq = bull_fvg_sequence() + [make_candle(4, o=103, h=103.5, l=100, c=100.5)]
        init = [make_box(Direction.BULL, 101, 104, formed_at_index=2)]

        r1 = detect_fvg_events(seq, init)
        r2 = detect_fvg_events(seq, init)

        self.assertEqual(r1.events, r2.events)
        self.assertEqual(r1.boxes, r2.boxes)

    def test_t18_no_mutation_of_inputs(self):
        seq = bull_fvg_sequence()
        init = [make_box(Direction.BULL, 101, 104, formed_at_index=2)]
        seq_snapshot = copy.deepcopy(seq)
        init_snapshot = copy.deepcopy(init)

        detect_fvg_events(seq, init)

        self.assertEqual(seq, seq_snapshot, "入参 K 线不得被修改")
        self.assertEqual(init, init_snapshot, "入参初始盒子不得被修改")


if __name__ == "__main__":
    unittest.main()
