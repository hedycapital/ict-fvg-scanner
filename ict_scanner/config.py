"""应用配置：环境变量加载 + 自解析 .env（不依赖 python-dotenv）。

环境变量一览（详见 .env.example）：
  SYMBOLS              可选白名单，逗号分隔（如 BTCUSDT,ETHUSDT）；设置后跳过 Top N 拉取
  TOP_N                默认 100：24h 成交额 Top N 作为扫描标的
  TIMEFRAME            K 线周期，固定 15m（本期不改 - YAGNI）
  TELEGRAM_BOT_TOKEN   Telegram Bot Token
  TELEGRAM_CHAT_ID     Telegram Chat ID
  DRY_RUN              1/true 时不推送、不落盘，仅打印
  STATE_PATH           state.json 路径，默认 ./state.json
  KLINE_LIMIT_COLD     冷启动拉取 K 线根数，默认 1500（约 15.6 天）
  HTTPS_PROXY / HTTP_PROXY 代理（大陆本地调试用；Requests 原生识别，此处仅透传）
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_ENV_FILE_NAME = ".env"


def _parse_env_file(path: Path) -> dict[str, str]:
    """极简 .env 解析：KEY=VALUE，支持注释行与两侧引号剥离。存在同名真实环境变量时以环境变量优先。"""
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            result[key] = value
    return result


def _load_env() -> dict[str, str]:
    """先读 CWD 下 .env（CI 无此文件，直接跳过），真实环境变量优先。"""
    file_env = _parse_env_file(Path.cwd() / _ENV_FILE_NAME)
    merged = dict(file_env)
    merged.update({k: v for k, v in os.environ.items() if v != ""})
    return merged


def _get_bool(env: dict[str, str], key: str) -> bool:
    return env.get(key, "").strip().lower() in ("1", "true", "yes", "on")


def _get_int(env: dict[str, str], key: str, default: int) -> int:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(slots=True)
class AppConfig:
    """全局配置（一次构建，处处只读）。"""

    symbols: list[str] = field(default_factory=list)  # 为空 = 使用 Top N
    top_n: int = 100
    timeframe: str = "15m"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    dry_run: bool = False
    state_path: Path = Path("state.json")
    kline_limit_cold: int = 1500

    # 检测器参数（与 Pine 脚本 input 一致）
    max_boxes: int = 3          # 盒子数组容量，超出先进先出挤出
    displacement_ratio: float = 0.6  # 位移过滤：body > range * 0.6（严格大于）


def load_config(env_file_dir: Path | None = None) -> AppConfig:
    """从环境变量（含 .env 文件）构建配置。env_file_dir 仅供测试注入。"""
    if env_file_dir is not None:
        file_env = _parse_env_file(env_file_dir / _ENV_FILE_NAME)
        env = dict(file_env)
        env.update({k: v for k, v in os.environ.items() if v != ""})
    else:
        env = _load_env()

    symbols_raw = env.get("SYMBOLS", "").strip()
    symbols = [s.strip().upper() for s in symbols_raw.split(",") if s.strip()] if symbols_raw else []

    return AppConfig(
        symbols=symbols,
        top_n=_get_int(env, "TOP_N", 100),
        timeframe=env.get("TIMEFRAME", "15m").strip() or "15m",
        telegram_bot_token=env.get("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=env.get("TELEGRAM_CHAT_ID", "").strip(),
        dry_run=_get_bool(env, "DRY_RUN"),
        state_path=Path(env.get("STATE_PATH", "state.json").strip() or "state.json"),
        kline_limit_cold=_get_int(env, "KLINE_LIMIT_COLD", 1500),
    )
