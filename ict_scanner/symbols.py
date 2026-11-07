"""标的解析：白名单优先，否则 24h 成交额 Top N。

白名单（env SYMBOLS）非空时直接使用（用户显式指定，不校验交易状态——
用户自负其责，K 线拉取失败会被单标的捕获）。
否则：ticker/24hr 全量 → 仅保留 exchangeInfo 中 status=TRADING 的永续合约
→ 按 quoteVolume（USDT 成交额）降序 → Top N。
"""

from __future__ import annotations

from .binance_client import BinanceClient
from .config import AppConfig


def resolve_symbols(config: AppConfig, client: BinanceClient) -> list[str]:
    if config.symbols:
        return list(config.symbols)

    tickers = client.get_ticker_24hr()
    trading = _trading_symbols(client)

    ranked = sorted(
        (t for t in tickers if t["symbol"] in trading),
        key=lambda t: float(t.get("quoteVolume", 0.0)),
        reverse=True,
    )
    return [t["symbol"] for t in ranked[: config.top_n]]


def _trading_symbols(client: BinanceClient) -> set[str]:
    try:
        info = client.get_exchange_info()
        return {
            s["symbol"]
            for s in info.get("symbols", [])
            if s.get("status") == "TRADING" and s.get("contractType") == "PERPETUAL"
        }
    except Exception:
        # exchangeInfo 失败不阻断：退化为全量 ticker（可能含下架标的，拉 K 线时被单点捕获）
        return set()
