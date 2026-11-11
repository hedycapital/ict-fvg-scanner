"""ICT FVG 缺口扫描系统 — TradingView Pine Script「ICT 大周期缺口雷达」1:1 移植。

扫描 Hyperliquid HIP-3（Trade[XYZ]）1 小时已收盘 K 线，
检测 FVG 缺口形成（FORMATION，仅后台记录）与价格回补触及（MITIGATION，推送），
通过 Telegram 推送通知。
"""

__version__ = "2.0.0"
