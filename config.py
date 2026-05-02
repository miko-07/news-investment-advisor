"""
新闻投资建议系统 - 配置管理
加载 .env 环境变量，提供统一配置入口
"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


# ── DeepSeek API ────────────────────────────────────────────
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# ── 网易邮箱 SMTP ───────────────────────────────────────────
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.163.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")  # 授权码，不是登录密码
SMTP_TO = os.getenv("SMTP_TO", "")  # 收件人

# ── 新闻源配置 ──────────────────────────────────────────────
# type: "rss" = feedparser 解析, "json" = HTTP JSON API
# 每个源独立超时，常被墙的源可以调小超时
NEWS_SOURCES = [
    # ── 国内财经 ──
    {
        "name": "财联社-电报",
        "type": "json",
        "url": "https://www.cls.cn/nodeapi/updateTelegraphList",
        "timeout": 10,
    },
    {
        "name": "新浪财经-宏观",
        "type": "json",
        "url": "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2512&k=&num=20&page=1",
        "timeout": 10,
    },
    {
        "name": "新浪财经-股票",
        "type": "json",
        "url": "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2511&k=&num=20&page=1",
        "timeout": 10,
    },
    {
        "name": "新浪财经-理财",
        "type": "json",
        "url": "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2510&k=&num=20&page=1",
        "timeout": 10,
    },
    {
        "name": "新浪财经-国际",
        "type": "json",
        "url": "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2514&k=&num=20&page=1",
        "timeout": 10,
    },
    # ── 科技/创投 ──
    {
        "name": "36氪",
        "type": "rss",
        "url": "https://36kr.com/feed",
        "timeout": 10,
    },
    # ── 国际财经（需外网）──
    {
        "name": "日经中文网",
        "type": "rss",
        "url": "https://cn.nikkei.com/rss.html",
        "timeout": 8,
    },
    {
        "name": "Yahoo Finance",
        "type": "rss",
        "url": "https://finance.yahoo.com/news/rssindex",
        "timeout": 8,
    },
    {
        "name": "Investing.com",
        "type": "rss",
        "url": "https://www.investing.com/rss/news_14.rss",
        "timeout": 8,
    },
    {
        "name": "Forexlive",
        "type": "rss",
        "url": "https://www.forexlive.com/feed",
        "timeout": 8,
    },
    # ── 国际新闻（中文，需外网）──
    {
        "name": "BBC中文",
        "type": "rss",
        "url": "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml",
        "timeout": 8,
    },
]

# ── 新闻抓取设置 ────────────────────────────────────────────
MAX_ARTICLES_PER_SOURCE = 15   # 每个源最多取几条
MAX_TOTAL_ARTICLES = 50        # 总共最多取几条
NEWS_MAX_AGE_HOURS = 24        # 只保留最近 N 小时内的新闻
REQUEST_TIMEOUT = 15           # 默认 HTTP 请求超时（秒）

# ── AI 分析设置 ────────────────────────────────────────────
AI_MAX_TOKENS = 4096
AI_TEMPERATURE = 0.3

# ── 输出文件（调试用）──────────────────────────────────────
OUTPUT_DIR = BASE_DIR / "output"
