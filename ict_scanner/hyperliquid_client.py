"""Hyperliquid 公开 REST 客户端（info 端点，无需 API Key）。

仅使用 POST /info 三个查询类型：
  perpDexs 不需要；实际用：
  - metaAndAssetCtxs {dex}      HIP-3 dex 元信息 + 行情（标的宇宙 / 24h 成交额）
  - candleSnapshot  {req}       K 线（coin="dex:asset"，如 "xyz:TSLA"）

限速策略：
  - HL 公开限速宽松（~1200 req/min/IP）；单轮 ~143 标的 × 2 次调用，安全。
  - 429：指数退避重试。
  - info 端点错误时通常仍返回 HTTP 200 + body {"error": "..."}，必须检查。

已收盘判定：candleSnapshot 无 close_time，用 t + 周期 <= now 推导（scanner 职责）。
"""

from __future__ import annotations

import time

import requests

from .models import INTERVAL_MS

API_URL = "https://api.hyperliquid.xyz"
DEFAULT_TIMEOUT = 15
MAX_RETRIES = 3

_RETRY_BACKOFF = (1.0, 2.0, 4.0)


class HyperliquidError(RuntimeError):
    """Hyperliquid API 业务错误（body 含 error / 非 JSON / 其他异常响应）。"""


class RateLimitError(HyperliquidError):
    """多次重试后仍被限速（429）。继承业务错误——scanner 单标的捕获可一并覆盖。"""


class HyperliquidClient:
    def __init__(self, api_url: str = API_URL, timeout: int = DEFAULT_TIMEOUT):
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        # 代理：Requests 原生读取 HTTPS_PROXY/HTTP_PROXY 环境变量，无需额外配置。

    # ------------------------------------------------------------------
    def _info(self, body: dict) -> requests.Response:
        backoff_iter = iter(_RETRY_BACKOFF)
        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self.session.post(
                    f"{self.api_url}/info", json=body, timeout=self.timeout
                )
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < MAX_RETRIES:
                    time.sleep(next(backoff_iter))
                continue

            if resp.status_code == 429:
                last_exc = HyperliquidError(f"429 rate limited: {resp.text[:200]}")
                if attempt < MAX_RETRIES:
                    time.sleep(next(backoff_iter) * 4)  # 限速等待更久
                continue

            if resp.status_code >= 400:
                raise HyperliquidError(f"{resp.status_code} /info: {resp.text[:300]}")
            return resp
        raise RateLimitError(f"/info 重试 {MAX_RETRIES} 次后仍失败: {last_exc}")

    def _info_json(self, body: dict):
        """POST /info 并解析 JSON；HL 错误时 HTTP 200 + {"error": ...}，统一转为异常。"""
        data = self._info(body).json()
        if isinstance(data, dict) and "error" in data:
            raise HyperliquidError(f"/info {body.get('type')}: {data['error']}")
        return data

    # ------------------------------------------------------------------
    def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int,
        end_time: int | None = None,
    ) -> list[dict]:
        """拉取 K 线原始数组（升序，元素为 {"t","o","h","l","c","v"} dict）。

        与原币安客户端同签名：limit 根 → 换算为对齐周期边界的时间范围
        （startTime 取整到周期开盘刻度），恰好返回最近 limit 根 + 当前未收盘那根。
        end_time 为毫秒时间戳，缺省用当前时间。
        """
        end = end_time if end_time is not None else int(time.time() * 1000)
        start = (end - limit * INTERVAL_MS) // INTERVAL_MS * INTERVAL_MS
        data = self._info_json({
            "type": "candleSnapshot",
            "req": {
                "coin": symbol,
                "interval": interval,
                "startTime": start,
                "endTime": end,
            },
        })
        candles = list(data) if isinstance(data, list) else []
        candles.sort(key=lambda k: int(k["t"]))  # 防御：确保升序（调用方依赖）
        return candles

    def get_dex_markets(self, dex: str) -> list[tuple[str, float, bool]]:
        """HIP-3 dex 标的宇宙：[(name, dayNtlVlm 24h 成交额, isDelisted), ...]。

        meta.universe 与 assetCtxs 同序 zip。
        """
        data = self._info_json({"type": "metaAndAssetCtxs", "dex": dex})
        meta, ctxs = data[0], data[1]
        markets: list[tuple[str, float, bool]] = []
        for u, c in zip(meta.get("universe", []), ctxs):
            markets.append(
                (u.get("name", ""), float(c.get("dayNtlVlm", 0.0) or 0.0),
                 bool(u.get("isDelisted", False)))
            )
        return markets
