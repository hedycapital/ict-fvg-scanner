"""ICT FVG 缺口扫描系统 — TradingView Pine Script「ICT 大周期缺口雷达」1:1 移植。

扫描币安 U 本位永续合约 15 分钟已收盘 K 线，
检测新 FVG 缺口形成（FORMATION）与价格回补触及已有缺口（MITIGATION），
通过 Telegram 推送通知。
"""

__version__ = "1.0.0"
