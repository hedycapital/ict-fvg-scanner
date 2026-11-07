"""扫描状态持久化。

关键设计（防静默漏检）：
  state 必须保存【活跃盒子】而不只是时间戳——窗口外形成的"悬空缺口"
  （如 6 天前形成未回补）不在重算窗口内，若只存时间戳，其被触及的
  那一轮会漏检。重算时把 state 盒子作为 initial_boxes 注入检测器。

结构（每标的独立）：
  {
    "version": 1,
    "symbols": {
      "BTCUSDT": {
        "last_candle_open_utc": 1699999999000,   # 最后已处理 K 线 open_time ms
        "boxes": [                                # 活跃盒子（老→新序）
          {"direction": "BULL", "bottom": 101.0, "top": 104.0,
           "formed_at_open_time": 1699999999000}
        ]
      }
    }
  }

写盘原子性：tmp 文件 + os.replace（同目录，进程崩溃不留半个文件）。
读取容错：文件缺失/损坏/版本不符 → 返回空 state（冷启动降级，宁重勿漏）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .models import Box, Direction

_STATE_VERSION = 1


class ScanState:
    """内存态：symbol → (last_candle_open_utc, boxes)。"""

    def __init__(self) -> None:
        self._data: dict[str, dict] = {}

    def get(self, symbol: str) -> tuple[int, list[Box]] | None:
        entry = self._data.get(symbol)
        if entry is None:
            return None
        boxes = [
            Box(
                direction=Direction(b["direction"]),
                bottom=float(b["bottom"]),
                top=float(b["top"]),
                formed_at_open_time=int(b["formed_at_open_time"]),
            )
            for b in entry.get("boxes", [])
        ]
        return int(entry["last_candle_open_utc"]), boxes

    def set(self, symbol: str, last_candle_open_utc: int, boxes: list[Box]) -> None:
        self._data[symbol] = {
            "last_candle_open_utc": last_candle_open_utc,
            "boxes": [
                {
                    "direction": b.direction.value,
                    "bottom": b.bottom,
                    "top": b.top,
                    "formed_at_open_time": b.formed_at_open_time,
                }
                for b in boxes
            ],
        }

    @property
    def symbol_count(self) -> int:
        return len(self._data)


def load_state(path: Path) -> ScanState:
    """加载 state；缺失/损坏/版本不符一律降级为空 state（冷启动）。"""
    state = ScanState()
    if not path.is_file():
        return state
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("version") != _STATE_VERSION:
            return state
        for symbol, entry in raw.get("symbols", {}).items():
            if not isinstance(entry, dict) or "last_candle_open_utc" not in entry:
                continue
            state.set(
                symbol,
                int(entry["last_candle_open_utc"]),
                [
                    Box(
                        direction=Direction(b["direction"]),
                        bottom=float(b["bottom"]),
                        top=float(b["top"]),
                        formed_at_open_time=int(b["formed_at_open_time"]),
                    )
                    for b in entry.get("boxes", [])
                ],
            )
    except (json.JSONDecodeError, KeyError, ValueError, TypeError, AttributeError):
        return ScanState()  # 损坏 → 冷启动
    return state


def save_state(path: Path, state: ScanState) -> None:
    """原子落盘：tmp + os.replace。"""
    payload = {
        "version": _STATE_VERSION,
        "symbols": state._data,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
