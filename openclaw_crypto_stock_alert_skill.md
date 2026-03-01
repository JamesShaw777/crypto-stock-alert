# OpenClaw Skill 设计与落地：Crypto + 股票价格告警

## 目标

实现一个 OpenClaw 技能，支持：

1. 获取 crypto 与股票价格
2. 设置阈值告警（高于/低于）
3. 定期检查价格（默认每 5 分钟）
4. 超过阈值时自动发送提醒
5. 多数据源 fallback（主源失败自动切换）

## 已落地文件

- 技能定义：`/root/.openclaw/workspace/skills/crypto-stock-alert/SKILL.md`
- 核心脚本：`/root/.openclaw/workspace/skills/crypto-stock-alert/scripts/market_alert.py`

## 数据源选择（含 fallback）

### Crypto 价格

按顺序尝试：

1. Yahoo Finance chart API
2. CoinGecko simple price API
3. Coinbase spot price API
4. Binance ticker API

### 股票价格

按顺序尝试：

1. Yahoo Finance chart API
2. Nasdaq quote API
3. Stooq CSV API

说明：任何单一源返回失败（超时/限流/格式异常）时，会自动尝试下一源。

## 告警机制

- 规则类型：`above` / `below`
- 触发策略：边沿触发（false -> true 时提醒）
- 防刷屏：若价格持续在阈值同侧，不重复提醒
- 重置条件：价格回到另一侧后再次穿越阈值，会再次提醒
- 并发保护：`check` 带文件锁，避免并发执行导致重复提醒

## 状态文件

脚本运行时自动维护：

- `~/.openclaw/skills-data/crypto-stock-alert/alerts.json`
- `~/.openclaw/skills-data/crypto-stock-alert/status.json`
- `~/.openclaw/skills-data/crypto-stock-alert/check.log`

## 命令示例

### 1) 查询价格

```bash
python3 /root/.openclaw/workspace/skills/crypto-stock-alert/scripts/market_alert.py quote BTC --type crypto
python3 /root/.openclaw/workspace/skills/crypto-stock-alert/scripts/market_alert.py quote AAPL --type stock
```

### 2) 设置告警（示例：BTC > 50000）

```bash
python3 /root/.openclaw/workspace/skills/crypto-stock-alert/scripts/market_alert.py add \
  --type crypto --symbol BTC --above 50000 \
  --channel telegram --target @your_chat
```

### 3) 定期检查（每 5 分钟）

```bash
python3 /root/.openclaw/workspace/skills/crypto-stock-alert/scripts/market_alert.py install-cron --minutes 5
```

### 4) 立即检查（调试）

```bash
python3 /root/.openclaw/workspace/skills/crypto-stock-alert/scripts/market_alert.py check --dry-run
python3 /root/.openclaw/workspace/skills/crypto-stock-alert/scripts/market_alert.py check
```

### 5) 查看 / 删除告警

```bash
python3 /root/.openclaw/workspace/skills/crypto-stock-alert/scripts/market_alert.py list
python3 /root/.openclaw/workspace/skills/crypto-stock-alert/scripts/market_alert.py rm <alert_id>
```

## 与用户对话映射（OpenClaw）

用户说：

> 设置一个警告，当比特币价格超过 50000 美元时提醒我。

OpenClaw 应执行：

1. 解析为：`type=crypto`，`symbol=BTC`，`above=50000`
2. 执行 `add` 命令创建告警
3. 执行 `install-cron --minutes 5` 确保周期检查
4. 执行 `check --dry-run` 回报当前检查结果

如果当前会话可用 channel/target（如 Telegram chat id），应直接写入 `--channel/--target`，使提醒能自动投递。
