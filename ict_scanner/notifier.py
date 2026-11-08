"""Telegram 推送：HTML 消息、4000 字符分片、3 次重试。

时序契约（与 scanner 约定）：send_scan_report 失败必须抛异常，
调用方以此决定是否落盘（先推送后落盘，宁重勿漏）。
"""

from __future__ import annotations

import datetime as dt
import html
import time
from urllib.parse import quote

import requests

from .config import AppConfig
from .models import Direction, EventType
from .scanner import SymbolOutcome

TELEGRAM_LIMIT = 4000      # 官方上限 4096，留余量
MAX_ATTEMPTS = 3
_RETRY_BACKOFF = (2.0, 4.0, 8.0)

_EVENT_ICON = {
    EventType.FORMATION: "🆕 形成",
    EventType.MITIGATION: "🎯 回补",
}
_DIR_ARROW = {Direction.BULL: "BULL ⬆", Direction.BEAR: "BEAR ⬇"}


def tv_chart_symbol(coin: str) -> str:
    """HIP-3 标的 → TradingView 交易所符号："xyz:TSLA" → "HIP3XYZ:TSLAUSDC.P"。

    TV 收录规则（已实测验证）：HIP3 + dex大写 为交易所名，合约后缀 USDC.P。
    仅 Trade[XYZ]（xyz dex）被 TV 收录；其他 dex 无对应图表。
    """
    dex, _, asset = coin.partition(":")
    return f"HIP3{dex.upper()}:{asset}USDC.P"


def tv_chart_url(coin: str) -> str:
    return f"https://www.tradingview.com/chart/?symbol={quote(tv_chart_symbol(coin), safe='')}"


def _fmt_ts(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%H:%M")


def _fmt_price(v: float) -> str:
    return f"{v:g}"


def build_blocks(outcomes: list[SymbolOutcome]) -> list[str]:
    """构建消息块（每块 ≤ 4000 字符）：标的为最小分组单元，块内按事件追加。"""
    header = (
        "📡 <b>ICT FVG 缺口雷达</b>  "
        + dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    )
    blocks: list[str] = []
    current = header

    for outcome in outcomes:
        # EVICTED（数组挤出）是内部生命周期事件，不推送
        pushable = [e for e in outcome.events if e.event_type is not EventType.EVICTED]
        if not pushable:
            continue
        # 标的名直接做成 TV 图表链接，点击即查看该合约 15m 图
        display = html.escape(outcome.symbol.partition(":")[2] or outcome.symbol)
        url = tv_chart_url(outcome.symbol)
        lines = [f'\n<b><a href="{url}">{display}</a></b>']
        for ev in pushable:
            b = ev.box
            label = _EVENT_ICON[ev.event_type]
            if ev.event_type is EventType.MITIGATION:
                label += {"BULL": "🟩", "BEAR": "🟥"}[b.direction.value]
            lines.append(
                f"{label} {b.direction.value} [{_fmt_price(b.bottom)}, {_fmt_price(b.top)}] "
                f"@ {_fmt_ts(ev.candle_open_time)}"
            )
        chunk = "\n".join(lines) + "\n"
        if len(current) + len(chunk) > TELEGRAM_LIMIT:
            blocks.append(current)
            current = header + chunk
        else:
            current += chunk
    if current.strip() != header.strip() or not blocks:
        blocks.append(current)
    return blocks


def _send_message(token: str, chat_id: str, text: str) -> None:
    """单条消息发送，3 次指数退避重试，全部失败抛异常。"""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    last_err: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code == 200:
                return
            last_err = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        except requests.RequestException as exc:
            last_err = exc
        if attempt < MAX_ATTEMPTS - 1:
            time.sleep(_RETRY_BACKOFF[attempt])
    raise RuntimeError(f"Telegram 推送失败（已重试 {MAX_ATTEMPTS} 次）: {last_err}")


def send_scan_report(config: AppConfig, outcomes: list[SymbolOutcome]) -> None:
    """推送全部事件。任一分片失败即抛异常（scanner 依赖此决定是否落盘）。"""
    blocks = build_blocks(outcomes)
    for i, block in enumerate(blocks, 1):
        _send_message(config.telegram_bot_token, config.telegram_chat_id, block)
        print(f"[notify] 分片 {i}/{len(blocks)} 已发送")
