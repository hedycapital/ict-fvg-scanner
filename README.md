# ICT FVG 缺口扫描系统（HIP-3 版）

TradingView Pine Script「ICT 大周期缺口雷达」的 Python 1:1 移植：
扫描 **Hyperliquid HIP-3 Trade[XYZ]**（美股代币 / 大宗商品 / 外汇永续合约）
1 小时已收盘 K 线，检测 **FVG 缺口形成**与**价格回补触及**，
经 **Windows 任务计划**每小时自动运行（仅**回补触及**触发推送，新缺口仅后台记录）。

## 数据源与标的宇宙

- **Hyperliquid HIP-3**：`api.hyperliquid.xyz` 公开 info 端点（无需密钥、不按地区封锁）
- **Trade[XYZ]（dex=xyz）**：约 143 个市场——美股代币（TSLA/NVDA/...）、ETF/指数
  （SP500/SOXL/...）、大宗商品（GOLD/SILVER/BRENTOIL/NATGAS/...）、外汇（EUR/GBP/JPY/...）
- 排除加密货币：HIP-3 为非加密资产永续；主流币在 HL 主 dex，不在本系统扫描范围
- 过滤 `isDelisted` 后全量扫描（约 122 个市场，按 24h 成交额降序）；
  可选流动性硬门槛 `MIN_VOLUME_USDC`（默认 0 = 不过滤）与 `TOP_N` 截断，
  白名单 `SYMBOLS` 显式指定时不受限

## TradingView 符号映射（推送链接）

| HIP-3 标的 | TV 交易所符号 | 推送链接 |
|---|---|---|
| `xyz:TSLA` | `HIP3XYZ:TSLAUSDC.P` | `https://www.tradingview.com/chart/?symbol=HIP3XYZ%3ATSLAUSDC.P` |
| `xyz:GOLD` | `HIP3XYZ:GOLDUSDC.P` | 同规则 |

规则：`HIP3` + dex 大写 为 TV 交易所名，合约后缀 `USDC.P`。仅 Trade[XYZ] 被 TV 收录。

## 检测逻辑（与 Pine 脚本严格一致）

```
三根 K 线引用: c0=当前, c1=前1根, c2=前2根
位移过滤:      abs(c1.close - c1.open) > (c1.high - c1.low) * 0.6   ← 严格大于

bull 缺口:     c0.low  > c2.high 且 c1 阳线 且 位移通过 → 盒子 [c2.high, c0.low]
bear 缺口:     c0.high < c2.low  且 c1 阴线 且 位移通过 → 盒子 [c0.high, c2.low]

数组容量 3:     超出则最老的被挤出（EVICTED，不推送）
缺口形成:       盒子入数组（FORMATION，仅 state 后台记录，不推送）
回补判定:       bull: c0.low  <= bottom → 触及即回补（MITIGATION，推送）
               bear: c0.high >= top    → 同上
每根 K 线执行序: 先创建（含挤出）→ 后填补（倒序 新→老）
```

细节语义见 `ict_scanner/fvg_detector.py` 文件头的 Pine 对照注释。

## 架构：无状态重算 + State 持久化

```
每轮: 拉 N 根已收盘 K 线 → 全量重算（事件日志）→ 过滤窗口事件
      → Telegram 推送 → state 落盘
```

- **state.json** 保存每标的 `最后处理K线时间 + 活跃盒子`——窗口外的"悬空缺口"
  依赖 state 注入才不漏检（关键设计，详见 `state.py`）
- **先推送后落盘**：推送失败 → 非零退出 → 不落盘 → 下轮窗口自动重推（宁重勿漏）
- **冷启动降级**：state 丢失时全量重算但只推最新一根的事件（防历史轰炸）
- **HL 无 close_time**：已收盘判定用 `开盘时间 + 1h <= now` 推导（不猜周期）
- **限速自愈**：单标的 429 失败不中断整轮，该标的 state 不推进 → 下轮自动补

## 目录结构

```
ict_scanner/
  models.py            # 数据模型（Candle/Box/FvgEvent，无 I/O）
  config.py            # env 加载 + 自解析 .env
  hyperliquid_client.py # HL /info 客户端（candleSnapshot / metaAndAssetCtxs，429 退避）
  fvg_detector.py      # ★ Pine 1:1 移植核心（纯函数）
  state.py             # state 原子读写（损坏降级冷启动）
  symbols.py           # 白名单优先，否则 xyz dex 全宇宙按成交额排序
  notifier.py          # Telegram HTML 推送（TV 链接 + 4000 字符分片 × 3 次重试）
  scanner.py           # 编排层
  cli.py / cli_verify.py / __main__.py
tests/                 # 19 个单测（检测器边界 + 窗口机制 + 推送分片/链接）
register_task.ps1 / run_scan.bat / run_scan_hidden.vbs   # Windows 任务计划链
```

## 本地运行

```bash
pip install -r requirements.txt

# 1. TV 一致性比对（最重要）
python -m ict_scanner verify --symbol xyz:TSLA

# 2. 试运行（不推送不落盘）
DRY_RUN=1 SYMBOLS=xyz:TSLA,xyz:GOLD python -m ict_scanner scan

# 3. 生产（需先配置 .env，参考 .env.example）
python -m ict_scanner scan

# 4. 全部单测
python -m unittest discover tests -v
```

> 大陆网络调试：在 `.env` 设置 `HTTPS_PROXY=http://127.0.0.1:7897`。

## 生产部署：Windows 任务计划（当前采用 ✅）

适用：交易监控机常开；HL API 与 Telegram 均可经代理直连。

```powershell
# 1. 配置 .env（复制 .env.example 填写 TELEGRAM_* 与 HTTPS_PROXY）
# 2. 注册任务（每小时 :05 触发——1h K 线 :00 收盘 + 5 分钟数据落定缓冲）
powershell -ExecutionPolicy Bypass -File register_task.ps1

# 管理
Get-ScheduledTask ICT-FVG-Scan          # 查看状态
Enable-ScheduledTask ICT-FVG-Scan       # 启用（TV 比对通过后）
Disable-ScheduledTask ICT-FVG-Scan      # 暂停（如重新比对期间）
Start-ScheduledTask ICT-FVG-Scan        # 手动触发
Unregister-ScheduledTask ICT-FVG-Scan -Confirm:$false   # 卸载
```

组成：`register_task.ps1`（注册）→ `run_scan_hidden.vbs`（无窗口包装）→
`run_scan.bat`（UTF-8 注意：bat 必须 ASCII-only）→ `python -m ict_scanner scan`。

### 备选：GitHub Actions

Hyperliquid 不按地区封锁——Actions 海外 runner **可直连**（无币安时代的 451 问题）。
`.github/workflows/fvg-scan.yml` 已配好 cron + state cache（restore/save 分离），
推到 GitHub 配置 Secrets 即可作为云端备份路径。

## TV 一致性验证流程（里程碑闸门）

数据源对齐：HL `candleSnapshot` 与 TV `HIP3XYZ:<ASSET>USDC.P` 同源、UTC 整点刻度对齐，
**理论零差异**；本流程为人工最终确认。

1. TV 打开 `HIP3XYZ:TSLAUSDC.P`，周期 **1h**，图表时区切 **UTC**；
2. 本地跑 `python -m ict_scanner verify --symbol xyz:TSLA`；
3. 逐项核对：
   - ① 最新 3 根已收盘 K 线 OHLC ↔ TV 当前 K 线
   - ② 活跃缺口列表 ↔ TV 图表现存 FVG 盒子（位置 + 形成时间）
   - ③ 事件日志 ↔ TV 上已消失的盒子（回补/挤出时间）
4. 换 `xyz:GOLD`（商品）与 `xyz:EUR`（外汇）重复。

若某项不一致，优先检查：TV 脚本 input 参数（maxBoxes=3、位移 0.6、严格版）。

## 设计决策记录

| 决策 | 结论 | 理由 |
|---|---|---|
| 数值类型 | float（IEEE double） | 与 Pine/HL 位级一致，Decimal 反而引入差异 |
| 已收盘判定 | `open_time + 1h <= now` | HL 无 close_time 字段，推导不猜周期 |
| 悬空缺口 | state 保存活跃盒子并注入重算 | 只存时间戳会在回补那根静默漏检 |
| EVICTED | 入事件日志但不推送 | 与 TV"盒子消失"行为一致，推送无意义 |
| FORMATION | 仅 state 后台记录，不推送 | 1h 周期下新缺口仍属高频；只推"二次回踩"这一价格实际反应的瞬间，防泛滥 |
| 流动性过滤 | 逻辑内置但默认关闭（阈值 0） | 保留按 `MIN_VOLUME_USDC`/`TOP_N` 过滤的能力，默认全市场扫描，需要时改 env 即开 |
| 排除加密货币 | 只扫 HIP-3 xyz dex | 用户需求：美股代币/商品/外汇 |
| TV 链接 | `HIP3<DEX>:<SYM>USDC.P` | TV symbol-search 实测收录规则 |

## 迁移记录（2026-11）

自币安 U 本位永续整体迁移至 Hyperliquid HIP-3（用户需求变更：排除加密货币）：
删除 `binance_client.py` 与 `worker/` 反代，新增 `hyperliquid_client.py`；
state.json 键空间变更（`BTCUSDT` → `xyz:TSLA`），旧 state 直接废弃冷启动。

### v2 降噪改版（2026-11-11）

推送频率治理：周期 15m → **1h**（`INTERVAL_MS` + `TIMEFRAME` + 调度同步）；
**FORMATION 降级**为 state 后台记录，仅 MITIGATION 触达推送（`models.PUSHABLE_EVENT_TYPES`）；
新增流动性过滤能力 `MIN_VOLUME_USDC` / `TOP_N`（默认 0 = 全市场）；
state 版本 1 → 2（旧时间戳与新周期刻度失配，强制全量冷启动重建，首轮不轰炸）。

## 扩展点（本期不实现）

脚本 1「狙击版」的 PDH/PDL 扫荡、杀手区过滤：`fvg_detector` 的
纯函数+事件日志模式可直接复用——新增 detector 与 EventType，编排层零改动。
