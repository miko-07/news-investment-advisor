# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Daily automated pipeline that scrapes Chinese/international financial news, analyzes it via DeepSeek API, formats the output for WeChat Official Account, and emails it to the user. Has two independent pipelines:

- **Morning report** (7:00 AM): Forward-looking daily investment briefing with stock picks
- **Closing review** (15:10 PM, trading days only): After-market recap with "expectation gap" analysis

Both run via macOS launchd.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env       # then edit .env with your API keys
```

## Key commands

```bash
# Morning pipeline
python3 main.py                          # Full pipeline: fetch → analyze → enrich → format → email
python3 main.py --dry-run                 # Same but skip email, save to output/
python3 main.py --test                    # Test with hardcoded sample news (no email)
python3 main.py --test-send               # Send latest output/ HTML + .md attachment as test email
python3 main.py --install-launchd         # Register macOS launchd daily 7AM job

# Closing review pipeline
python3 main.py --closing-review          # Run closing review with email
python3 main.py --closing-review --dry-run  # Run closing review, no email
python3 main.py --install-launchd-review  # Register launchd for trading-day 15:10

# Other
python3 news_fetcher.py                   # Test news fetching standalone (prints formatted articles)
python3 viewer.py                         # Start history viewer at http://localhost:8899
python3 viewer.py <port>                  # Start on custom port
```

## Architecture

### Morning pipeline (`main.py:run_pipeline`)

```
news_fetcher.py      analyzer.py         price_fetcher.py        formatter.py       email_sender.py
(fetch_all_news)  →  (analyze_news)  →   (fetch_prices +     →  (markdown_to_    →  (send_email)
                     [6-section MD]       fetch_daily_trends)     wechat_html)
                                          ↓
                                       analyzer.py
                                       (enrich_with_prices)
                                       [append 七、买卖策略参考]
```

4 steps but with a 2.5-stage price enrichment that fetches real-time quotes for recommended stocks and appends a buy/sell strategy section.

### Closing review pipeline (`main.py:run_closing_review`)

```
news_fetcher.py      price_fetcher.py    analyzer.py                 formatter.py       email_sender.py
(fetch_all_news)  →  (fetch_market_   →  (analyze_closing_review) → (markdown_to_    → (send_email)
                     [6 major indices     [6-section review,         wechat_html)
                     实时行情]              + morning report context
                     早报) ↑                + real-time index prices]
                           └──── morning_analysis ───┘
```

3-step pipeline with two optional enrichment sources:
- **Market snapshot**: 6 major indices (上证, 深证, 创业板, 上证50, 沪深300, 科创50) fetched via `price_fetcher.py:fetch_market_snapshot()`, injected into the prompt so the model references precise closing prices rather than fabricating them
- **Morning report context**: if `output/analysis_{date_key}.md` exists, its first 4 sections (标题→风险预警) are included for "预期对比" analysis

### Article dict schema

Shared across the pipeline: `{title, source, url, summary, published}`. `published` is a timezone-aware `datetime` or `None`.

### Caching

`run_pipeline()` checks `output/analysis_{date_key}.html` before running. If exists → reuse + optionally re-send. If only `.md` exists → skip fetch + analyze, regenerate HTML. `run_closing_review()` does the same with `output/review_{date_key}` prefix — independent caches.

### Error resilience

DeepSeek API calls have 3 retries with exponential backoff (1s, 2s, 4s). News fetching uses 4-thread `ThreadPoolExecutor` — foreign sources with 8s timeout fail fast, don't block domestic sources. `run.log` auto-rotates at 5MB (3 backups).

## News source system (`news_fetcher.py`)

Sources declared in `config.py:NEWS_SOURCES`. Each source has `type: "rss"` or `type: "json"`. RSS uses `feedparser`; JSON needs a parser function registered in `_JSON_PARSERS` dict (keyed by domain substring). Currently two JSON parsers: `_parse_cls` for cls.cn and `_parse_sina` for sina.com.cn. Adding a new JSON source requires writing its parser and mapping its domain in `_JSON_PARSERS`.

Fetching is parallel (4 workers). Custom `_HTTP1Adapter` forces TLS 1.2 + HTTP/1.1 ALPN to avoid SSL EOF errors on some Chinese CDNs. `_http_get()` retries `SSLError` 3 times (1s+ jitter). Deduplication is O(1) set-based on first 15 chars of title. Articles older than `NEWS_MAX_AGE_HOURS` (24h) filtered out. Results truncated to `MAX_TOTAL_ARTICLES` (50).

Working sources (11 total):
- 国内直连: 财联社 CLS API, 4×新浪财经 JSON (宏观/股票/理财/国际), 36氪 RSS
- 需外网: 日经中文网 RSS, Yahoo Finance RSS, Investing.com RSS, Forexlive RSS, BBC中文 RSS
- Foreign sources have 8s timeout — fail fast when VPN is off
- Pipeline proceeds as long as ≥5 articles total, so domestic-only mode still works

## DeepSeek integration (`analyzer.py`)

Uses OpenAI Python SDK pointed at `https://api.deepseek.com`. Three independent analysis stages, each with its own system prompt:

### Stage 1: Morning news analysis (`analyze_news`)
System prompt casts model as senior macro strategist. Enforces **no-prices rule** (model is offline, must not fabricate prices). 6-section Markdown output:
1. 市场情绪速览
2. 关键新闻解读 (5-8 items, each with impact + advice)
3. 板块与品种机会
4. 风险预警
5. 今日策略
6. 推荐股票池 (Markdown table: 名称/代码/推荐理由)

### Stage 2: Price enrichment (`enrich_with_prices`)
Called after Stage 1 if stock codes are extracted from the recommendation table. Fetches real-time quotes + daily trend data via `price_fetcher.py` (新浪财经 API). Appends a `## 七、买卖策略参考` section with buy ranges, stop-loss, target prices, and position sizing. Failures are silent — the pipeline keeps the base report.

### Stage 3: Closing review (`analyze_closing_review`)
Separate system prompt for post-market review. Focuses on "预期差" — what happened vs what was expected. Receives three optional enrichment sources:
- **Morning report** (`morning_analysis`): first 4 sections of the day's morning report for direct "预期对比"
- **Market snapshot** (`price_snapshot`): real-time index prices from `fetch_market_snapshot()` — model must cite these numbers, not fabricate
- System prompt enforces data integrity: "所有价格、涨跌幅、成交量等必须来自上方提供的行情数据，不得编造"

6 output sections:
1. 今日市场复盘
2. 核心催化剂回顾 (with 预期对比)
3. 板块轮动与资金特征
4. 今日市场异动观察
5. 明日关键观察点
6. 持仓策略修正

Model settings: `AI_TEMPERATURE=0.3` (low for consistency), `AI_MAX_TOKENS=4096`.

## Price fetching (`price_fetcher.py`)

Fetches real-time A/HK/US stock quotes from 新浪财经 API (`hq.sinajs.cn`). Also fetches 5-day daily K-line trends from 东方财富 API. Key functions:
- `codes_to_sina(stock_codes)` — converts codes like `600519.SH` to sina format `sh600519`
- `fetch_prices(sina_codes)` — real-time quotes (current price, change, high, low, volume)
- `fetch_daily_trends(sina_codes)` — 5-day OHLCV data
- `compute_trend_summary(trends)` — support/resistance levels, MA, trend direction
- `format_trends_for_ai(prices, summaries)` — formats data for the AI prompt
- `fetch_market_snapshot()` — fetches 6 major indices (via `MARKET_INDEX_CODES`) and returns a Markdown table; used by the closing review to inject precise closing prices into the prompt, preventing the model from fabricating numbers

## WeChat HTML formatting (`formatter.py`)

## WeChat HTML formatting (`formatter.py`)

Custom Markdown→HTML converter (not a library). Handles: h1-h3, bold/italic, code, fenced code blocks, escaped chars, lists with multi-line item support (indented continuations), blockquotes, horizontal rules, links, and Markdown tables. Output has inline CSS for WeChat Official Account paste and email clients. Weekly recurring "weekly digest" placeholder exists for special formatting.

## Report viewer (`viewer.py`)

Flask app at `http://localhost:8899`. 
- `/` — card list of all reports in `output/`, with sentiment tags (偏多/偏空/震荡) and source labels (定时/测试/复盘)
- `/report/<filename>` — full report from pre-generated HTML. `Path.resolve()` prevents path traversal.
- Handles `analysis_*`, `review_*`, and `test_analysis_*` filename prefixes

## Scheduling

Uses macOS **launchd** (not cron). Two plists:
- `com.news.investment-advisor` — daily at 7:00 (morning report)
- `com.news.investment-advisor.review` — Mon-Fri at 15:10 (closing review, with runtime trading-day check via `chinese_calendar`)

launchd chosen over cron because it catches missed jobs when the machine wakes from sleep.

Management:
```
launchctl list | grep news                          # status
launchctl start com.news.investment-advisor         # manual morning
launchctl start com.news.investment-advisor.review  # manual review
launchctl bootout gui/$(id -u)/com.news.investment-advisor{,.review}  # remove
```

## Configuration

- `.env` — secrets (DEEPSEEK_API_KEY, SMTP credentials). Never committed.
- `.env.example` — template for above.
- `config.py` — all tunable parameters: news source list, `NEWS_MAX_AGE_HOURS` (24h), fetch limits, AI model settings (temperature 0.3, model name), SMTP defaults.
- `run.log` — execution log (auto-rotated at 5MB, 3 backups).
- `output/` — contains `analysis_YYYYMMDD.md/.html` and `review_YYYYMMDD.md/.html`.

## Timezone convention

All internal timestamps are converted to CST (UTC+8, `timezone(timedelta(hours=8))`). Display format: `%Y年%m月%d日` for dates, `%m-%d %H:%M` for times.
