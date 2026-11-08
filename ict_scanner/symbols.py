"""标的解析：白名单优先，否则 HIP-3 dex 全宇宙按 24h 成交额降序（TOP_N=0 即全部）。

白名单（env SYMBOLS）非空时直接使用（用户显式指定，可省略 dex 前缀——
"TSLA" 自动补为 "xyz:TSLA"；拉 K 线失败会被单标的捕获）。
否则：metaAndAssetCtxs {dex} → 过滤 isDelisted → 按 dayNtlVlm 降序 → Top N / 全部。

标的完整名 = f"{dex}:{asset}"（candleSnapshot 的 coin 参数要求带 dex 前缀）。
"""

from __future__ import annotations

from .config import AppConfig
from .hyperliquid_client import HyperliquidClient


def normalize_symbol(raw: str, dex: str) -> str:
    """规范标的完整名："TSLA" → "xyz:TSLA"；已带前缀的统一 dex 小写 + asset 大写。"""
    s = raw.strip()
    if ":" in s:
        prefix, _, asset = s.partition(":")
        return f"{prefix.lower()}:{asset.upper()}"
    return f"{dex.lower()}:{s.upper()}"


def resolve_symbols(config: AppConfig, client: HyperliquidClient) -> list[str]:
    if config.symbols:
        return [normalize_symbol(s, config.hip3_dex) for s in config.symbols]

    markets = client.get_dex_markets(config.hip3_dex)
    listed = [(name, vlm) for name, vlm, delisted in markets if not delisted]
    ranked = sorted(listed, key=lambda m: m[1], reverse=True)
    if config.top_n > 0:
        ranked = ranked[: config.top_n]
    # universe[].name 自带 dex 前缀（如 "xyz:TSLA"），normalize 兜底去重
    return [normalize_symbol(name, config.hip3_dex) for name, _ in ranked]
