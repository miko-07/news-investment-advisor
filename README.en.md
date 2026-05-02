# 📊 Daily News Investment Advisor

[中文](README.md) · [English](README.en.md)

Automated financial news analysis and email delivery system. Scrapes Chinese and international financial news daily, analyzes them via DeepSeek AI, generates structured investment reports, and sends them via email.

## Features

- **Morning Briefing** (7:00 AM): Market sentiment analysis, key news breakdown, sector opportunities, risk warnings, trading strategy, stock picks
- **Closing Review** (trading days at 3:10 PM): End-of-day market recap, catalyst review, expectation gap analysis, next-day outlook, position adjustment suggestions
- **Live Price Enhancement**: Fetches real-time quotes + 5-day K-line trends for recommended stocks, appends buy/sell strategy
- **History Viewer**: Web UI to browse past reports

## Quick Start

```bash
pip install -r requirements.txt
cp .env.example .env        # edit .env with your API keys and SMTP credentials
python3 main.py --dry-run   # test run (no email)
```

## Usage

```bash
python3 main.py                           # Full pipeline (fetch → analyze → enrich → format → email)
python3 main.py --dry-run                  # Same but skip email, save to output/
python3 main.py --test                     # Test with sample data
python3 main.py --closing-review           # Run closing review
python3 main.py --test-send                # Send latest report as test email
python3 main.py --install-launchd          # Install launchd job (daily at 7:00)
python3 main.py --install-launchd-review   # Install review job (trading days 15:10)
python3 viewer.py                          # Start history viewer (http://localhost:8899)
```

## Data Sources (11)

| Source | Type | Region |
|--------|------|--------|
| CLS (财联社) | JSON | China direct |
| Sina Finance (macro/stocks/finance/global) | JSON | China direct |
| 36Kr | RSS | China direct |
| Nikkei Chinese | RSS | Requires VPN |
| Yahoo Finance | RSS | Requires VPN |
| Investing.com | RSS | Requires VPN |
| Forexlive | RSS | Requires VPN |
| BBC Chinese | RSS | Requires VPN |

## Tech Stack

- **Language**: Python 3.12+
- **AI**: DeepSeek API (OpenAI SDK)
- **Scraping**: requests, feedparser, BeautifulSoup
- **Scheduling**: macOS launchd
- **Visualization**: Flask
- **Email**: SMTP (163 mail)

## Project Structure

```
├── config.py           # Central config (sources, AI params, SMTP)
├── news_fetcher.py     # Multi-source parallel news scraping
├── analyzer.py         # DeepSeek 3-stage analysis (morning/price/review)
├── price_fetcher.py    # Real-time quotes + K-line trends
├── formatter.py        # Markdown → WeChat-compatible HTML
├── email_sender.py     # SMTP email sender
├── main.py             # Pipeline orchestration, CLI, launchd
├── viewer.py           # Flask history report viewer
└── output/             # Generated reports (.md + .html)
```

## Configuration

Configure via `.env`:

```
DEEPSEEK_API_KEY=sk-xxx
SMTP_HOST=smtp.163.com
SMTP_PORT=465
SMTP_USER=xxx@163.com
SMTP_PASSWORD=authorization_code      # Not your login password
SMTP_TO=xxx@163.com
```

## License

MIT
