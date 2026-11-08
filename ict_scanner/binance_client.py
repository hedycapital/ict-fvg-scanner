"""币安 U 本位永续合约（fapi）公开 REST 客户端。

仅使用公开接口（无需 API Key）：
  GET /fapi/v1/klines          K 线
  GET /fapi/v1/ticker/24hr     24h 滚动行情（用于成交额 Top N）
  GET /fapi/v1/exchangeInfo    合约元信息（交易状态过滤）

限速策略：
  - 币安权重限制 2400/min；单轮 ~100 标的 × klines(limit<=1500, 权重10) ≈ 1000 权重，安全。
  - HTTP 429/418：按响应头 Retry-After 精确等待后重试（币安官方建议）。
  - 其他网络错误：指数退避重试。
"""

from __future__ import annotations

import time

import requests

FAPI_BASE_URL = "https://fapi.binance.com"
DEFAULT_TIMEOUT = 15
MAX_RETRIES = 3


class BinanceError(RuntimeError):
    """币安 API 业务错误（非限速类）。"""


class RateLimitError(RuntimeError):
    """多次重试后仍被限速（429/418）。"""


class BinanceClient:
    def __init__(
        self,
        base_url: str = FAPI_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
        proxy_key: str = "",
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.proxy_key = proxy_key
        self.session = requests.Session()
        # 代理：Requests 原生读取 HTTPS_PROXY/HTTP_PROXY 环境变量，无需额外配置。
        # 大陆本地调试设置 HTTPS_PROXY 即可；Actions 海外 runner 不受影响。

    # ------------------------------------------------------------------
    def _get(self, path: str, params: dict | None = None) -> requests.Response:
        url = self.base_url + path
        if params is None:
            params = {}
        if self.proxy_key:
            # 反代防滥用密钥：Worker 校验后剥离，不会透传到币安
            params = {**params, "key": self.proxy_key}
        backoff = 1.0
        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                last_exc = exc
                time.sleep(backoff)
                backoff *= 2
                continue

            if resp.status_code in (429, 418):
                retry_after = _parse_retry_after(resp)
                time.sleep(retry_after)
                last_exc = BinanceError(f"{resp.status_code} rate limited: {resp.text[:200]}")
                continue

            if resp.status_code >= 400:
                raise BinanceError(f"{resp.status_code} {path}: {resp.text[:300]}")
            return resp
        raise RateLimitError(f"{path} 重试 {MAX_RETRIES} 次后仍失败: {last_exc}")

    # ------------------------------------------------------------------
    def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int,
        end_time: int | None = None,
    ) -> list[list]:
        """拉取 K 线原始数组（升序）。end_time 为毫秒时间戳，返回该时刻之前（含）的 K 线。"""
        params: dict = {"symbol": symbol, "interval": interval, "limit": limit}
        if end_time is not None:
            params["endTime"] = end_time
        return self._get("/fapi/v1/klines", params).json()

    def get_ticker_24hr(self) -> list[dict]:
        """全量 24h 滚动行情。字段：symbol / quoteVolume / lastPrice 等。"""
        return self._get("/fapi/v1/ticker/24hr").json()

    def get_exchange_info(self) -> dict:
        """合约元信息：symbols[].status == 'TRADING' 才是可交易合约。"""
        return self._get("/fapi/v1/exchangeInfo").json()


def _parse_retry_after(resp: requests.Response) -> float:
    """读取 Retry-After 头（秒），缺失时退避 10s。"""
    raw = resp.headers.get("Retry-After")
    if raw:
        try:
            return max(float(raw), 1.0)
        except ValueError:
            pass
    return 10.0
