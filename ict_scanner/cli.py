"""CLI 子命令定义与分发。

子命令：
  scan    生产运行：扫描并推送 Telegram，更新 state（CI 使用）
  verify  TV 比对工具：输出最新收盘 K 线 / 活跃缺口 / 历史事件，供人工核对
"""

import argparse
import sys


def _setup_stdio() -> None:
    """Windows 控制台默认 GBK，统一为 UTF-8 避免中文乱码（Linux 无影响）。"""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ict_scanner",
        description="ICT FVG 缺口扫描系统（Hyperliquid HIP-3 美股代币/商品/外汇 / 1h 已收盘 K 线）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("scan", help="生产扫描：检测事件 → Telegram 推送 → state 落盘")
    verify_parser = sub.add_parser(
        "verify", help="TV 一致性比对工具：打印 K 线 / 活跃缺口 / 历史事件"
    )
    from .cli_verify import build_verify_parser

    build_verify_parser(verify_parser)
    return parser


def main(argv: list[str]) -> int:
    _setup_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "scan":
        from .scanner import run_scan

        return run_scan()
    if args.command == "verify":
        from .cli_verify import run_verify

        return run_verify(symbol=args.symbol, limit=args.limit, interval=args.interval)
    parser.error(f"未知命令: {args.command}")
    return 2
