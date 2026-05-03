#!/usr/bin/env python3
"""
每日新闻投资参考 — 主流程
用法:
  python main.py                    # 执行一次完整流程（抓取→分析→格式化→发邮件）
  python main.py --dry-run           # 执行但不发邮件，结果保存到 output/
  python main.py --test              # 使用样例数据测试全流程
  python main.py --install-launchd   # 安装 macOS 定时任务（每天早 7:00）
  python viewer.py                   # 启动历史报告可视化页面 (http://localhost:8899)
"""
import argparse
import logging
import re
import os
import sys
from datetime import datetime, timezone, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import OUTPUT_DIR, SMTP_USER, SMTP_TO, BASE_DIR
from news_fetcher import fetch_all_news, format_news_for_ai
from analyzer import analyze_news, analyze_closing_review, extract_stock_codes, enrich_with_prices
from price_fetcher import (
    fetch_prices, fetch_daily_trends, compute_trend_summary,
    codes_to_sina, format_trends_for_ai, fetch_market_snapshot,
)
from formatter import markdown_to_wechat_html
from email_sender import send_email

CST = timezone(timedelta(hours=8))


def _extract_title(markdown_text: str) -> str:
    """从 Markdown 中提取 H1 标题，去除 📊 前缀"""
    match = re.search(r"^# (.+)$", markdown_text, re.MULTILINE)
    if not match:
        return "每日投资参考"
    title = match.group(1).strip()
    title = re.sub(r"^📊\s*", "", title)
    return title if title else "每日投资参考"


def is_trading_day() -> bool:
    """判断今天是否是 A 股交易日（周一至周五，且非中国法定节假日）"""
    try:
        import chinese_calendar
        return chinese_calendar.is_workday(datetime.now(CST).date())
    except ImportError:
        # Fallback: 仅判断工作日
        return datetime.now(CST).weekday() < 5


# ── 日志配置 ──────────────────────────────────────────────
LOG_FILE = BASE_DIR / "run.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(LOG_FILE, encoding="utf-8", maxBytes=5*1024*1024, backupCount=3),
    ],
)
logger = logging.getLogger("main")


def _save_analysis(analysis_md: str, date_str: str, date_key: str, basename: str = "") -> str:
    """保存分析结果为 .md 和 .html 文件，返回 HTML 内容"""
    html_body = markdown_to_wechat_html(analysis_md, date_str)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    basename = basename or f"analysis_{date_key}"
    md_path = OUTPUT_DIR / f"{basename}.md"
    html_path = OUTPUT_DIR / f"{basename}.html"
    md_path.write_text(analysis_md, encoding="utf-8")
    html_path.write_text(html_body, encoding="utf-8")

    logger.info(f"结果已保存: {md_path.name}, {html_path.name}")
    return html_body


def run_pipeline(send: bool = True) -> dict:
    """执行完整流水线，返回结果字典"""
    now = datetime.now(CST)
    date_str = now.strftime("%Y年%m月%d日")
    date_key = now.strftime("%Y%m%d")

    result = {"date": date_str, "success": False}

    # ── 缓存策略 ──
    md_path = OUTPUT_DIR / f"analysis_{date_key}.md"
    html_path = OUTPUT_DIR / f"analysis_{date_key}.html"

    if html_path.exists():
        logger.info(f"当日报告已存在: {html_path.name}")
        html_body = html_path.read_text(encoding="utf-8")
        result["html_body"] = html_body
        if send:
            logger.info("发送邮件（复用已有 HTML）...")
            title = _extract_title(md_path.read_text(encoding="utf-8")) if md_path.exists() else "每日投资参考"
            subject = f"📊 {title}"
            try:
                send_email(subject, html_body, md_file_path=str(md_path))
                result["success"] = True
                logger.info("流水线执行完毕 ✓")
            except Exception as e:
                logger.error(f"邮件发送失败: {e}")
                result["error"] = str(e)
        else:
            result["success"] = True
        return result

    if md_path.exists():
        logger.info("检测到当日分析缓存，跳过抓取和 AI 分析")
        analysis_md = md_path.read_text(encoding="utf-8")
        result["analysis_md"] = analysis_md
    else:
        # ── Step 1: 抓取新闻 ──
        logger.info("=" * 50)
        logger.info(f"开始执行 {date_str} 新闻投资参考流水线")
        logger.info("=" * 50)

        logger.info("[Step 1/4] 抓取新闻...")
        articles = fetch_all_news()

        if len(articles) < 5:
            logger.error(f"新闻数量不足（{len(articles)} 条），中止执行")
            result["error"] = "新闻数量不足"
            return result

        news_text = format_news_for_ai(articles)
        result["articles"] = articles
        result["news_text"] = news_text

        # ── Step 2: AI 分析 ──
        logger.info("[Step 2/4] DeepSeek AI 分析中...")
        analysis_md = analyze_news(articles, date_str, news_text)
        result["analysis_md"] = analysis_md

        # ── Step 2.5: 获取推荐股票实时行情 + 近期走势 → 追加买卖策略 ──
        stock_codes = extract_stock_codes(analysis_md)
        if stock_codes:
            logger.info(f"[Step 2.5/4] 获取 {len(stock_codes)} 只推荐股票行情及走势...")
            sina_codes = codes_to_sina(stock_codes)
            prices = fetch_prices(sina_codes)
            if prices:
                trends = fetch_daily_trends(sina_codes)
                trend_summaries = compute_trend_summary(trends)
                logger.info(
                    f"成功获取 {len(prices)} 只行情, {len(trend_summaries)} 只走势"
                )
                combined_text = format_trends_for_ai(prices, trend_summaries)
                enriched = enrich_with_prices(analysis_md, combined_text, date_str)
                if enriched:
                    analysis_md = enriched
                    result["analysis_md"] = analysis_md
                    result["prices"] = prices
                    logger.info("买卖策略已追加到报告")
                else:
                    logger.warning("策略生成失败，保留原报告")
            else:
                logger.warning("未能获取实时行情，保留原报告（方向性建议，无具体价格）")
        else:
            logger.info("未提取到推荐股票代码，跳过行情获取")

    # ── 统一追加免责声明（仅一次）──
    disclaimer = (
        "\n\n---\n\n"
        "**以上内容由 AI 基于公开新闻、实时行情和近期走势自动生成，"
        "仅供参考，不构成投资建议。投资有风险，决策须谨慎。**"
    )
    analysis_md = analysis_md.rstrip() + disclaimer

    # ── Step 3: 格式化为微信 HTML ──
    logger.info("[Step 3/4] 格式化为微信 HTML...")
    html_body = _save_analysis(analysis_md, date_str, date_key)
    result["html_body"] = html_body

    # ── Step 4: 发送邮件 ──
    if send:
        logger.info("[Step 4/4] 发送邮件...")
        title = _extract_title(analysis_md)
        subject = f"📊 {title}"
        try:
            send_email(subject, html_body, md_file_path=str(md_path))
            result["success"] = True
            logger.info("流水线执行完毕 ✓")
        except Exception as e:
            logger.error(f"邮件发送失败: {e}")
            result["error"] = str(e)
    else:
        logger.info("[Step 4/4] 跳过发送（dry-run 模式）")
        result["success"] = True

    return result


def run_closing_review(send: bool = True) -> dict:
    """执行收盘复盘流水线（收盘后 15:10 推送）"""
    now = datetime.now(CST)
    date_str = now.strftime("%Y年%m月%d日")
    date_key = now.strftime("%Y%m%d")

    result = {"date": date_str, "success": False, "type": "review"}

    # ── 复盘报告缓存（独立于早报）──
    review_basename = f"review_{date_key}"
    md_path = OUTPUT_DIR / f"{review_basename}.md"
    html_path = OUTPUT_DIR / f"{review_basename}.html"

    if html_path.exists():
        logger.info(f"当日复盘报告已存在: {html_path.name}")
        html_body = html_path.read_text(encoding="utf-8")
        result["html_body"] = html_body
        if send:
            logger.info("发送复盘邮件（复用已有 HTML）...")
            title = _extract_title(md_path.read_text(encoding="utf-8")) if md_path.exists() else "收盘复盘"
            subject = f"📋 复盘 | {title}"
            try:
                send_email(subject, html_body, md_file_path=str(md_path))
                result["success"] = True
                logger.info("复盘流水线执行完毕 ✓")
            except Exception as e:
                logger.error(f"复盘邮件发送失败: {e}")
                result["error"] = str(e)
        else:
            result["success"] = True
        return result

    if md_path.exists():
        logger.info("检测到当日复盘缓存，跳过抓取和 AI 分析")
        analysis_md = md_path.read_text(encoding="utf-8")
        result["analysis_md"] = analysis_md
    else:
        logger.info("=" * 50)
        logger.info(f"开始执行 {date_str} 收盘复盘流水线")
        logger.info("=" * 50)

        # Step 1: 抓取新闻
        logger.info("[Step 1/3] 抓取新闻...")
        articles = fetch_all_news()

        if len(articles) < 5:
            logger.error(f"新闻数量不足（{len(articles)} 条），中止复盘")
            result["error"] = "新闻数量不足"
            return result

        news_text = format_news_for_ai(articles)
        result["articles"] = articles
        result["news_text"] = news_text

        # Step 1.5: 获取实时行情索引快照
        logger.info("[Step 1.5/3] 获取实时行情数据...")
        price_snapshot = fetch_market_snapshot()
        if price_snapshot:
            logger.info("行情快照获取成功，将注入复盘分析")
        else:
            logger.info("行情快照获取失败，仅基于新闻分析")

        # Step 2: AI 复盘分析（含早报上下文 + 实时行情）
        logger.info("[Step 2/3] DeepSeek AI 复盘分析中...")
        morning_path = OUTPUT_DIR / f"analysis_{date_key}.md"
        morning_text = morning_path.read_text(encoding="utf-8") if morning_path.exists() else None
        analysis_md = analyze_closing_review(
            articles, date_str, news_text,
            morning_analysis=morning_text,
            price_snapshot=price_snapshot,
        )
        result["analysis_md"] = analysis_md

    # ── 追加免责声明 ──
    disclaimer = (
        "\n\n---\n\n"
        "**以上内容由 AI 基于当日公开新闻自动生成，"
        "仅供参考，不构成投资建议。投资有风险，决策须谨慎。**"
    )
    analysis_md = analysis_md.rstrip() + disclaimer

    # Step 3: 格式化为微信 HTML 并保存
    logger.info("[Step 3/3] 格式化为微信 HTML...")
    html_body = _save_analysis(analysis_md, date_str, date_key, basename=review_basename)
    result["html_body"] = html_body

    # Step 4: 发送邮件
    if send:
        logger.info("发送复盘邮件...")
        title = _extract_title(analysis_md)
        subject = f"📋 复盘 | {title}"
        try:
            send_email(subject, html_body, md_file_path=str(md_path))
            result["success"] = True
            logger.info("复盘流水线执行完毕 ✓")
        except Exception as e:
            logger.error(f"复盘邮件发送失败: {e}")
            result["error"] = str(e)
    else:
        logger.info("跳过发送（dry-run 模式）")
        result["success"] = True

    return result


def run_test():
    """使用样例数据测试全流程"""
    logger.info("=" * 50)
    logger.info("测试模式：使用样例数据")
    logger.info("=" * 50)

    now = datetime.now(CST)
    date_str = now.strftime("%Y年%m月%d日")
    date_key = now.strftime("%Y%m%d")

    # 模拟新闻数据
    test_articles = [
        {"title": "美联储维持利率不变，暗示年内降息",
         "source": "Reuters", "url": "", "summary": "美联储FOMC会议决定维持基准利率在5.25%-5.5%不变，鲍威尔表示通胀正在向2%目标靠拢",
         "published": datetime.now(timezone.utc)},
        {"title": "A股三大指数收涨，北向资金净流入超80亿",
         "source": "新浪财经", "url": "", "summary": "沪指涨0.85%，深成指涨1.21%，北向资金连续5日净流入",
         "published": datetime.now(timezone.utc)},
        {"title": "国际金价突破2500美元创历史新高",
         "source": "Bloomberg", "url": "", "summary": "地缘政治紧张叠加央行购金潮，现货黄金突破2500美元/盎司",
         "published": datetime.now(timezone.utc)},
        {"title": "国务院出台新举措支持新能源产业发展",
         "source": "财联社", "url": "", "summary": "国务院常务会议审议通过新能源汽车、光伏等产业扶持政策",
         "published": datetime.now(timezone.utc)},
        {"title": "日本央行意外加息，日元短线飙升",
         "source": "Reuters", "url": "", "summary": "日本央行将利率从0.1%上调至0.25%，日元兑美元短线升值1.5%",
         "published": datetime.now(timezone.utc)},
        {"title": "中央汇金宣布增持四大行股份",
         "source": "华尔街见闻", "url": "", "summary": "中央汇金公司公告称近期增持工商银行、农业银行、中国银行、建设银行A股股份",
         "published": datetime.now(timezone.utc)},
        {"title": "美国4月CPI低于预期，市场押注9月降息",
         "source": "Bloomberg", "url": "", "summary": "美国4月CPI同比3.4%，低于预期的3.6%，利率期货显示9月降息概率升至75%",
         "published": datetime.now(timezone.utc)},
    ]

    news_text = format_news_for_ai(test_articles)
    logger.info("→ 调用 DeepSeek 分析...")
    analysis_md = analyze_news(test_articles, date_str, news_text)
    logger.info("→ 转换为微信 HTML...")
    _save_analysis(analysis_md, date_str, date_key, basename="test_analysis_" + date_key)

    logger.info(f"测试完成，结果保存至 {OUTPUT_DIR}/")
    logger.info("如需发送测试邮件，请运行: python main.py --test-send")


def test_send():
    """发送 output/ 下最新的 HTML 文件作为测试邮件"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    html_files = sorted(OUTPUT_DIR.glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not html_files:
        logger.error("没有找到 HTML 输出文件，请先运行 --test 或 --dry-run")
        return

    latest = html_files[0]
    html_body = latest.read_text(encoding="utf-8")
    date_str = datetime.now(CST).strftime("%Y年%m月%d日")
    md_file = latest.with_suffix(".md")
    title = _extract_title(md_file.read_text(encoding="utf-8")) if md_file.exists() else "每日投资参考"
    subject = f"📊 {title}（测试）"

    logger.info(f"发送测试邮件: {latest.name}")
    send_email(subject, html_body, md_file_path=str(md_file) if md_file.exists() else None)


def install_launchd():
    """
    安装 macOS launchd 定时任务（推荐，比 cron 更可靠）
    电脑睡眠唤醒后会自动补执行错过的任务
    """
    import subprocess

    python = sys.executable
    main_py = str(BASE_DIR / "main.py")
    plist_name = "com.news.investment-advisor"
    plist_path = Path.home() / f"Library/LaunchAgents/{plist_name}.plist"

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{plist_name}</string>

    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>-u</string>
        <string>{main_py}</string>
    </array>

    <key>WorkingDirectory</key>
    <string>{BASE_DIR}</string>

    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>7</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>

    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>"""

    logger.info("安装 macOS launchd 定时任务（每天早 7:00）...")
    logger.info(f"  Python:    {python}")
    logger.info(f"  主程序:    {main_py}")
    logger.info(f"  plist:     {plist_path}")

    # 写入 plist
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(plist_content, encoding="utf-8")

    # 加载到 launchd
    try:
        uid = os.getuid()
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{plist_name}"],
                       capture_output=True, text=True)
        subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)],
                       capture_output=True, text=True, check=True)
        logger.info("✓ launchd 定时任务安装成功！每天早上 7:00 自动执行")
        logger.info("")
        logger.info("  查看状态: launchctl list | grep news")
        logger.info("  手动触发: launchctl start com.news.investment-advisor")
        logger.info(f"  卸载任务: launchctl bootout gui/$(id -u)/com.news.investment-advisor")
    except subprocess.CalledProcessError as e:
        logger.error(f"launchd 加载失败: {e.stderr}")
        logger.info(f"plist 文件已写入 {plist_path}，请手动加载:")
        logger.info(f"  launchctl bootstrap gui/$(id -u) {plist_path}")


def install_launchd_review():
    """
    安装 macOS launchd 定时任务：A股交易日收盘后 15:10 自动执行复盘
    """
    import subprocess

    python = sys.executable
    main_py = str(BASE_DIR / "main.py")
    plist_name = "com.news.investment-advisor.review"
    plist_path = Path.home() / f"Library/LaunchAgents/{plist_name}.plist"

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{plist_name}</string>

    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>-u</string>
        <string>{main_py}</string>
        <string>--closing-review</string>
    </array>

    <key>WorkingDirectory</key>
    <string>{BASE_DIR}</string>

    <key>StartCalendarInterval</key>
    <array>
        <dict>
            <key>Hour</key>
            <integer>15</integer>
            <key>Minute</key>
            <integer>10</integer>
            <key>Weekday</key>
            <integer>1</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>15</integer>
            <key>Minute</key>
            <integer>10</integer>
            <key>Weekday</key>
            <integer>2</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>15</integer>
            <key>Minute</key>
            <integer>10</integer>
            <key>Weekday</key>
            <integer>3</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>15</integer>
            <key>Minute</key>
            <integer>10</integer>
            <key>Weekday</key>
            <integer>4</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>15</integer>
            <key>Minute</key>
            <integer>10</integer>
            <key>Weekday</key>
            <integer>5</integer>
        </dict>
    </array>

    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>"""

    logger.info("安装 macOS launchd 定时任务（交易日 15:10 复盘推送）...")
    logger.info(f"  Python:    {python}")
    logger.info(f"  主程序:    {main_py} --closing-review")
    logger.info(f"  plist:     {plist_path}")

    # 写入 plist
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(plist_content, encoding="utf-8")

    # 加载到 launchd
    try:
        uid = os.getuid()
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{plist_name}"],
                       capture_output=True, text=True)
        subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)],
                       capture_output=True, text=True, check=True)
        logger.info("✓ launchd 复盘定时任务安装成功！交易日 15:10 自动执行")
        logger.info("")
        logger.info("  查看状态: launchctl list | grep news")
        logger.info("  手动触发: launchctl start com.news.investment-advisor.review")
        logger.info(f"  卸载任务: launchctl bootout gui/$(id -u)/com.news.investment-advisor.review")
    except subprocess.CalledProcessError as e:
        logger.error(f"launchd 加载失败: {e.stderr}")
        logger.info(f"plist 文件已写入 {plist_path}，请手动加载:")
        logger.info(f"  launchctl bootstrap gui/$(id -u) {plist_path}")


def main():
    parser = argparse.ArgumentParser(
        description="每日新闻投资参考 — 自动抓取新闻、AI分析、邮件发送"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="执行全流程但不发邮件，结果保存到 output/"
    )
    parser.add_argument(
        "--test", action="store_true",
        help="使用样例数据测试全流程（不发邮件）"
    )
    parser.add_argument(
        "--test-send", action="store_true",
        help="发送 output/ 下最新的 HTML 作为测试邮件"
    )
    parser.add_argument(
        "--install-launchd", action="store_true",
        help="安装 macOS launchd 定时任务（推荐），每天早上 7:00 自动执行"
    )
    parser.add_argument(
        "--closing-review", action="store_true",
        help="执行收盘复盘流水线（A股收盘后 15:10 推送）"
    )
    parser.add_argument(
        "--install-launchd-review", action="store_true",
        help="安装收盘复盘 launchd 定时任务，交易日 15:10 自动执行"
    )

    args = parser.parse_args()

    # 检查必要配置
    if not _check_config():
        sys.exit(1)

    if args.test:
        run_test()
    elif args.test_send:
        test_send()
    elif args.install_launchd:
        install_launchd()
    elif args.install_launchd_review:
        install_launchd_review()
    elif args.closing_review:
        # 检查是否为交易日
        if not is_trading_day():
            logger.info("今天非 A 股交易日，跳过收盘复盘")
            return
        send = not args.dry_run
        run_closing_review(send=send)
    elif args.dry_run:
        run_pipeline(send=False)
    else:
        run_pipeline(send=True)


def _check_config() -> bool:
    """检查关键配置是否就绪"""
    import config
    ok = True

    if not config.DEEPSEEK_API_KEY:
        logger.error("❌ DEEPSEEK_API_KEY 未设置，请在 .env 文件中配置")
        ok = False
    if not config.SMTP_USER:
        logger.error("❌ SMTP_USER 未设置，请在 .env 文件中配置")
        ok = False
    if not config.SMTP_PASSWORD:
        logger.error("❌ SMTP_PASSWORD（网易邮箱授权码）未设置，请在 .env 文件中配置")
        ok = False

    return ok


if __name__ == "__main__":
    main()
