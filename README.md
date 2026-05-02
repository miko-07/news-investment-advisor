# 📊 每日新闻投资参考系统

自动化财经新闻分析与推送工具。每天定时抓取国内外财经新闻，通过 DeepSeek AI 分析，生成结构化的投资参考报告并通过邮件推送。

## 功能

- **早间晨报**（7:00 推送）：盘前市场情绪判断、关键新闻解读、板块机会、风险预警、策略建议、推荐股票池
- **收盘复盘**（交易日 15:10 推送）：当日市场走势复盘、核心催化剂回顾、预期差分析、明日关键观察点、持仓策略修正
- **实时行情增强**：获取推荐股票实时行情 + 5 日 K 线走势，追加买卖策略
- **历史查看器**：Web 页面浏览历史报告

## 快速开始

```bash
pip install -r requirements.txt
cp .env.example .env        # 编辑 .env 填入 API Key 和邮箱配置
python3 main.py --dry-run   # 测试运行（不发邮件）
```

## 使用

```bash
python3 main.py                           # 完整流水线（抓取→分析→行情增强→格式化→发邮件）
python3 main.py --dry-run                  # 同上，不发邮件，保存到 output/
python3 main.py --test                     # 使用样例数据测试
python3 main.py --closing-review           # 执行收盘复盘
python3 main.py --test-send                # 发送最新报告为测试邮件
python3 main.py --install-launchd          # 安装定时任务（每天 7:00）
python3 main.py --install-launchd-review   # 安装复盘定时任务（交易日 15:10）
python3 viewer.py                          # 启动历史报告查看器 (http://localhost:8899)
```

## 数据源（11 个）

| 名称 | 类型 | 地区 |
|------|------|------|
| 财联社-电报 | JSON | 国内直连 |
| 新浪财经（宏观/股票/理财/国际） | JSON | 国内直连 |
| 36氪 | RSS | 国内直连 |
| 日经中文网 | RSS | 需外网 |
| Yahoo Finance | RSS | 需外网 |
| Investing.com | RSS | 需外网 |
| Forexlive | RSS | 需外网 |
| BBC中文 | RSS | 需外网 |

## 技术栈

- **语言**: Python 3.12+
- **AI**: DeepSeek API（OpenAI SDK）
- **新闻抓取**: requests, feedparser, BeautifulSoup
- **定时调度**: macOS launchd
- **可视化**: Flask
- **邮件**: SMTP (163 邮箱)

## 项目结构

```
├── config.py           # 统一配置（信源列表、AI 参数、SMTP 等）
├── news_fetcher.py     # 多源并行新闻抓取
├── analyzer.py         # DeepSeek 三阶段分析（早报/行情增强/复盘）
├── price_fetcher.py    # 实时行情 + K 线走势获取
├── formatter.py        # Markdown → 微信 HTML
├── email_sender.py     # SMTP 邮件发送
├── main.py             # 流水线编排、CLI、launchd 管理
├── viewer.py           # Flask 历史报告查看器
└── output/             # 生成的分析报告（.md + .html）
```

## 配置

通过 `.env` 文件配置：

```
DEEPSEEK_API_KEY=sk-xxx
SMTP_HOST=smtp.163.com
SMTP_PORT=465
SMTP_USER=xxx@163.com
SMTP_PASSWORD=授权码      # 不是登录密码
SMTP_TO=xxx@163.com
```

## 许可

MIT
