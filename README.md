# ICT FVG 缺口扫描系统

TradingView Pine Script「ICT 大周期缺口雷达」的 Python 1:1 移植：
扫描**币安 U 本位永续合约** 15 分钟已收盘 K 线，检测 **FVG 缺口形成**与**价格回补触及**，
经 **GitHub Actions** 每 15 分钟自动运行并推送 **Telegram**。

## 检测逻辑（与 Pine 脚本严格一致）

```
三根 K 线引用: c0=当前, c1=前1根, c2=前2根
位移过滤:      abs(c1.close - c1.open) > (c1.high - c1.low) * 0.6   ← 严格大于

bull 缺口:     c0.low  > c2.high 且 c1 阳线 且 位移通过 → 盒子 [c2.high, c0.low]
bear 缺口:     c0.high < c2.low  且 c1 阴线 且 位移通过 → 盒子 [c0.high, c2.low]

数组容量 3:     超出则最老的被挤出（EVICTED，不推送）
回补判定:       bull: c0.low  <= bottom → 触及即回补（MITIGATION，推送）
               bear: c0.high >= top    → 同上
每根 K 线执行序: 先创建（含挤出）→ 后填补（倒序 新→老）
```

细节语义见 `ict_scanner/fvg_detector.py` 文件头的 Pine 对照注释。

## 架构：无状态重算 + Cache 持久化

```
每轮: 拉 N 根已收盘 K 线 → 全量重算（事件日志）→ 过滤窗口事件
      → Telegram 推送 → state 落盘
```

- **state.json** 保存每标的 `最后处理K线时间 + 活跃盒子`——窗口外的"悬空缺口"
  依赖 state 注入才不漏检（关键设计，详见 `state.py`）
- **先推送后落盘**：推送失败 → 非零退出 → 不落盘 → 下轮窗口自动重推（宁重勿漏）
- **cache restore/save 分离**：固定 key 命中后不再保存会导致 state 永不更新
  （见 workflow 注释）
- **冷启动降级**：cache 丢失时全量重算但只推最新一根的事件（防历史轰炸）

## 目录结构

```
ict_scanner/
  models.py         # 数据模型（Candle/Box/FvgEvent，无 I/O）
  config.py         # env 加载 + 自解析 .env
  binance_client.py # fapi REST 客户端（429/418 按 Retry-After 退避）
  fvg_detector.py   # ★ Pine 1:1 移植核心（纯函数）
  state.py          # state 原子读写（损坏降级冷启动）
  symbols.py        # 白名单优先，否则 24h 成交额 Top N
  notifier.py       # Telegram HTML 推送（4000 字符分片 × 3 次重试）
  scanner.py        # 编排层
  cli.py / cli_verify.py / __main__.py
tests/              # 16 个单测（检测器边界 + 窗口机制 + 推送分片）
.github/workflows/fvg-scan.yml
```

## 本地运行

```bash
pip install -r requirements.txt

# 1. TV 一致性比对（最重要）
python -m ict_scanner verify --symbol BTCUSDT

# 2. 试运行（不推送不落盘）
DRY_RUN=1 SYMBOLS=BTCUSDT,ETHUSDT python -m ict_scanner scan

# 3. 生产（需先配置 .env，参考 .env.example）
python -m ict_scanner scan

# 4. 全部单测
python -m unittest discover tests -v
```

> 大陆网络调试：在 `.env` 设置 `HTTPS_PROXY=http://127.0.0.1:7890`。

## 生产部署：两条路径

### 路径 A：本地 Windows 任务计划（当前采用 ✅）

适用：交易监控机常开；币安可直连（国内网络实测可达），仅 Telegram 走代理。

```powershell
# 1. 配置 .env（复制 .env.example 填写 TELEGRAM_* 与 HTTPS_PROXY）
# 2. 注册任务（对齐 :00/:15/:30/:45 收盘，无弹窗，日志写入 logs\scan.log）
powershell -ExecutionPolicy Bypass -File register_task.ps1

# 管理
Get-ScheduledTask ICT-FVG-Scan          # 查看状态
Start-ScheduledTask ICT-FVG-Scan        # 手动触发
Unregister-ScheduledTask ICT-FVG-Scan -Confirm:$false   # 卸载
```

组成：`register_task.ps1`（注册）→ `run_scan_hidden.vbs`（无窗口包装）→
`run_scan.bat`（UTF-8 注意：bat 必须 ASCII-only）→ `python -m ict_scanner scan`。

### 路径 B：GitHub Actions + Cloudflare Workers 反代

⚠️ **已知的坑**：GitHub 托管 runner 出口在美国，币安 fapi 直接返回
**451 Restricted Location**（runner 地区不可选），必须经反代访问：

1. 部署 `worker/binance-proxy.js` 到 Cloudflare Workers（文件头有步骤）；
2. 仓库 Secrets 配置 `BINANCE_BASE_URL`（workers.dev 地址）与
   `BINANCE_PROXY_KEY`（Worker 中 SCAN_KEY）；
3. workflow 每 15 分钟自动运行（cron 已配好，state 经 cache 持久化）。

Runner 出口在非受限地区时无需反代（`BINANCE_BASE_URL` 留空即用官方域名）。

## 部署步骤（Actions 路径通用部分）

1. **推送本仓库到 GitHub**。建议**公共仓库**——私有仓库 2000 分钟/月额度下
   每 15 分钟一轮（约 5040 轮/月 × 1~2 分钟）会超额；公共仓库 Actions 免费。

2. **配置 Secrets**（仓库 Settings → Secrets and variables → Actions）：
   | 名称 | 来源 |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | @BotFather 创建 Bot 获得 |
   | `TELEGRAM_CHAT_ID` | 给 @userinfobot 发消息查询；频道用 `-100` 开头 ID |

3. **（可选）配置 Variables**：
   | 名称 | 说明 | 默认 |
   |---|---|---|
   | `SYMBOLS` | 白名单（逗号分隔），设了就只扫这些 | 空 = Top 100 |
   | `TOP_N` | 24h 成交额 Top N | 100 |

4. **首次验证**：Actions 页 → `ICT FVG Scan` → `Run workflow` → 勾选
   `dry_run` → 观察 log：标的数 / 事件 / `DRY_RUN: 未推送、未落盘`。

5. **去掉 dry_run 再手动跑一轮** → Telegram 收到推送。

6. **观察 4~8 个周期**（1~2 小时）：无重复推送、无报错即部署完成。

## TV 一致性验证流程（M4 里程碑闸门）

数据同源性保证：币安 fapi 与 TV `BINANCE:xxxUSDT.P` 同源、UTC 对齐，
**理论零差异**；本流程为人工最终确认。

1. TV 打开 `BINANCE:BTCUSDT.P`，周期 **15m**，图表时区切 **UTC**；
2. 本地跑 `python -m ict_scanner verify --symbol BTCUSDT`；
3. 逐项核对：
   - ① 最新 3 根已收盘 K 线 OHLC ↔ TV 当前 K 线（含未收盘那根之外的前 3 根）
   - ② 活跃缺口列表 ↔ TV 图表现存 FVG 盒子（位置 + 形成时间）
   - ③ 事件日志 ↔ TV 上已消失的盒子（回补/挤出时间）
4. 换 `ETHUSDT` 与一个近期新上线标的（缺口稀疏场景）重复。

若某项不一致，优先检查：TV 脚本 input 参数（maxBoxes=3、位移 0.6、严格版）。

## 设计决策记录

| 决策 | 结论 | 理由 |
|---|---|---|
| 数值类型 | float（IEEE double） | 与 Pine/币安位级一致，Decimal 反而引入差异 |
| 已收盘判定 | `close_time <= now`（K 线自带时间） | 不信本地时钟猜周期 |
| 悬空缺口 | state 保存活跃盒子并注入重算 | 只存时间戳会在回补那根静默漏检 |
| EVICTED | 入事件日志但不推送 | 与 TV"盒子消失"行为一致，推送无意义 |
| runner 时区 | cron 全 UTC | GitHub Actions schedule 恒为 UTC |

## 扩展点（本期不实现）

脚本 1「狙击版」的 PDH/PDL 扫荡、杀手区过滤：`fvg_detector` 的
纯函数+事件日志模式可直接复用——新增 detector 与 EventType，编排层零改动。
