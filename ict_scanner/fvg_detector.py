"""FVG 缺口检测器 — TradingView Pine Script「ICT 大周期缺口雷达」1:1 移植。

═══════════════════════════════════════════════════════════════════════
 原 Pine Script 核心逻辑对照（严格版，含位移过滤）
═══════════════════════════════════════════════════════════════════════

  // 三根 K 线引用：c0 = 当前 K 线，c1 = 前 1 根，c2 = 前 2 根
  body_1 = math.abs(c1.close - c1.open)
  range_1 = c1.high - c1.low
  is_displacement = body_1 > range_1 * displacementRatio   // 0.6，严格大于

  // bull 缺口：当前 K 线最低价完全越过 2 根前最高价，且 c1 为放量阳线
  bullFVG = c0.low  > c2.high and c1.close > c1.open and is_displacement
  // bear 缺口：当前 K 线最高价完全跌破 2 根前最低价，且 c1 为放量阴线
  bearFVG = c0.high < c2.low  and c1.close < c1.open and is_displacement

  // 盒子区间
  bull: bottom = c2.high, top = c0.low
  bear: bottom = c0.high, top = c2.low

  // 数组生命周期（maxBoxes = 3）
  boxes.push(box)
  if boxes.size() > maxBoxes:
      evicted = boxes.shift()          // 先进先出挤出 → EVICTED 事件（不推送）

  // 填补判定（同一根 K 线，创建之后执行；倒序 新→老）
  for i = boxes.size() - 1 to 0:       // 倒序保证 remove 索引安全
      box = boxes.get(i)
      bull 填补: c0.low  <= box.bottom → MITIGATION + remove
      bear 填补: c0.high >= box.top    → MITIGATION + remove
═══════════════════════════════════════════════════════════════════════

关键语义（与 Pine / IEEE double 完全一致，勿改动比较符）：
  1. 位移过滤是【严格大于】body > range * 0.6 —— body/range 恰好 0.6 不通过；
  2. 缺口创建是【严格大于】c0.low > c2.high —— 等号接触不算缺口；
  3. 填补是【小于等于】c0.low <= box.bottom —— 触及即视为回补并删除；
  4. 每根 K 线执行序固定：先创建（含挤出）→ 后填补遍历；
  5. bull/bear 创建条件数学上互斥，任一 K 线至多新建一个盒子；
  6. 新建盒子不可能在同一根 K 线被填补（创建与填补条件矛盾）；
  7. range_1 = 0 时 is_displacement 必为 False（body 同为 0），无除零风险。

纯函数设计：无 I/O、无时钟依赖、不修改入参；初始盒子（state 恢复）通过
initial_boxes 注入，从窗口第 1 根即参与填补判定（处理"悬空缺口"漏检）。
"""

from __future__ import annotations

from .models import Box, Candle, DetectionResult, Direction, EventType, FvgEvent


def _create_box(c0: Candle, c1: Candle, c2: Candle, ratio: float) -> Box | None:
    """按 Pine 条件判定 c0 处是否形成新缺口；返回 None 表示未形成。

    bull/bear 条件数学互斥（见模块注释第 5 条），此处统一判定。
    """
    body_1 = abs(c1.close - c1.open)
    range_1 = c1.high - c1.low
    is_displacement = body_1 > range_1 * ratio  # 严格大于（IEEE double，与 Pine 位级一致）

    if c0.low > c2.high and c1.close > c1.open and is_displacement:
        return Box(
            direction=Direction.BULL,
            bottom=c2.high,
            top=c0.low,
            formed_at_open_time=c0.open_time,
        )
    if c0.high < c2.low and c1.close < c1.open and is_displacement:
        return Box(
            direction=Direction.BEAR,
            bottom=c0.high,
            top=c2.low,
            formed_at_open_time=c0.open_time,
        )
    return None


def detect_fvg_events(
    candles: list[Candle],
    initial_boxes: list[Box] | None = None,
    max_boxes: int = 3,
    displacement_ratio: float = 0.6,
) -> DetectionResult:
    """对 K 线序列执行全量检测（Pine 数组生命周期逐根模拟）。

    参数:
        candles: 升序 K 线（时间递增，无重复）。
        initial_boxes: 上轮 state 恢复的活跃盒子（悬空缺口），参与填补判定但不重复推送 FORMATION。
        max_boxes: 盒子数组容量（Pine input maxBoxes=3），超出先进先出。
        displacement_ratio: 位移过滤系数（Pine input = 0.6）。

    返回:
        DetectionResult：events 为时间序事件日志（含 EVICTED，调用方自行过滤推送）；
        boxes 为结束时活跃盒子快照（老→新序，可直接存入 state）。
    """
    result = DetectionResult()
    boxes: list[Box] = list(initial_boxes or [])  # 数组序：老→新（push 尾部）
    injected_keys = {(b.direction, b.formed_at_open_time) for b in boxes}

    for i, c0 in enumerate(candles):
        # ── 阶段 1：创建（需要 [1]/[2] 引用，窗口前 2 根无法判定）──────────
        if i >= 2:
            c1 = candles[i - 1]
            c2 = candles[i - 2]
            new_box = _create_box(c0, c1, c2, displacement_ratio)
            if new_box is not None:
                key = (new_box.direction, new_box.formed_at_open_time)
                if key not in injected_keys:
                    injected_keys.add(key)
                    boxes.append(new_box)
                    result.events.append(
                        FvgEvent(EventType.FORMATION, new_box, c0.open_time)
                    )
                    if len(boxes) > max_boxes:
                        evicted = boxes.pop(0)
                        result.events.append(
                            FvgEvent(EventType.EVICTED, evicted, c0.open_time)
                        )
                # key 已存在（state 注入过的盒子在窗口内被重复模拟）→ 跳过，防止幽灵事件

        # ── 阶段 2：填补遍历（倒序 新→老，触及即回补删除）────────────────
        idx = len(boxes) - 1
        while idx >= 0:
            box = boxes[idx]
            if box.overlaps_candle(c0):
                result.events.append(
                    FvgEvent(EventType.MITIGATION, box, c0.open_time)
                )
                boxes.pop(idx)
            idx -= 1

    result.boxes = boxes
    return result
